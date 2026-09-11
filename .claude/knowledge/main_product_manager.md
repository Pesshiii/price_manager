# main_product_manager

`MainProduct` — the canonical product record. Highest-churn app in the repo
(171 of the last 200 commits touched it). Owns the PIM integration.

## `.save()` deliberately doesn't rebuild the search vector

`MainProduct.save()` (`models.py:178`) is a bare `super().save()` — don't
"fix" that by adding a rebuild call. `_build_searchvector()` makes a PIM
network call per row (CLAUDE.md's cross-app-dependencies note); adding it to
`save()` would turn every save in the codebase into an HTTP request. Trace
whether a loop over `MainProduct` reaches `rebuild_search_vector()`
(`models.py:172`) regardless of how cheap the queryset looked — that's one
round-trip per row. It builds `SearchVector(Value(supplier_name), ...)`
rather than `SearchVector('supplier__name')` because `bulk_update()` /
`.update()` don't allow joined fields in a SET expression (`:155-156`) —
switch to field references and the update fails at the DB layer, not import
time. `GinIndex` in `Meta.indexes` covers `search_vector`, `config='russian'`
(`models.py:44`).

## PIM scans run with `atomic=False` — moving the write is not enough

Hoisting `bulk_update` out of the API loop doesn't stop the transaction
spanning the HTTP calls — `execute_locked_task`'s transaction opens before
the runner is called regardless of where the write lands inside it. Fix is
`atomic=False` at the call site — see [[core]]:

- `tasks.py` `create_pim_links_task` → `utils.py` `create_pim_links`
- `tasks.py` `reindex_pim_ids_batch_task` → `utils.py` `reindex_pim_ids_batch`

Safe without the transaction because the Redis lock, not the transaction,
provides mutual exclusion, and both are idempotent re-scans that resume
cleanly from committed progress after a mid-loop failure (`_search_pim_id`'s
no-match cache writes escape a rollback anyway). Do **not** wrap
`push_missing_pim_products` (`_push_pim_products` underneath — HTTP,
`bulk_update` and `sleep` interleaved per chunk) in a transaction "to
compensate" — that breaks its promise that one failing chunk doesn't lose
the others. New PIM-touching tasks: pass `atomic=False` rather than
reshuffle writes.

## The PIM cache's render-path cost — and why it bites tests too

`get_pim_data` (`utils.py:133`) is synchronous on a cache miss or when
`refresh=True` — `_fetch_pim_product(...)` (`utils.py:141`) runs in-line, no
early return, so a cold cache blocks the request on a PIM HTTP round-trip.
`get_file_url` (`utils.py:347`) has the same shape on a miss (`:353`) but has
no queueing on either branch.

`prefetch_pim_data` (`utils.py:329`) loops products one at a time, and
`MainProductTableView.get_context_data` (`views.py:186`) then calls
`get_file_url` again per entry (`views.py:198`): up to **2N** PIM calls per
cold page (the main page paginates 5 categories at a time, `views.py:89`,
each firing its own `hx-trigger="load"` fetch, `tables_bycat.html:53,82`).
**But calls dedupe by `pim_id`/file id, not by row** — `get_pim_data` caches
on `pim_product:{pim_id}` (`:136`), `get_file_url` on `pim_file:{file_id}`
(`:351`) — so real cost is bounded by distinct `pim_id`s on the page.
`MainProductTable._pim` still reads `pim_map` by `record.pk` (`tables.py:231`).

**Rendering this table in a test makes live PIM HTTP calls unless patched.**
Tests run under `settings.prod` with the placeholder `PIM_TOKEN`/`PIM_HOST`,
so any test rendering `MainProductTable` with a `pim_id`-bearing product, or
calling `get_pim_data`/`get_file_url` directly, hits the network via the path
above unless patched — for the table,
`main_product_manager.views.prefetch_pim_data` and `.maybe_notify_pim_error`
(`test_grouping.py:29-30`); for `get_pim_data` itself, `_fetch_pim_product`
with an explicit `return_value=(data, not_found)` (it's unpacked as a
2-tuple). Creating `MainProduct`s is safe — `save()` doesn't reach PIM — but
a test needing a populated `search_vector` should set it directly with
`SearchVector` over local fields (`test_grouping.py:64-68`) instead of
calling `rebuild_search_vector()`.

**Fixed trap: the cache write and the population trigger must share a
branch.** `_queue_pim_population` has exactly one call site in the app —
`utils.py:152`, inside `get_pim_data`'s successful-fetch branch — and it's
the only thing that ever queues `populate_pim_relations_task`, itself the
only caller of `sync_pim_relations` (`utils.py:302`), itself the only code
that writes `MainProduct.manufacturer`/`.categories` from PIM data. Until
this fix, the call sat one level up, in the `if not refresh:` cache-miss
branch (`utils.py:137-140`) — reached by non-refresh callers
(`prefetch_pim_data`; `_build_searchvector` via `get_pim_data`,
`models.py:154`) only on a miss, but never by the two `refresh=True` callers,
`MainProductInfo`/`MainProductDetail` (`views.py:251,267`). Those views
warmed `pim_product:<pim_id>` for the full 24h `PIM_CACHE_TTL` on every visit
without ever queueing population — opening a product's detail page
suppressed that product's own manufacturer/categories sync for a day (see
issue #164's near-total absence of categories, cited in the `pim_id` section
below). Fix: move the call into the successful-fetch branch, right after
`cache.set`/`_note_pim_success` (`utils.py:143-152`), so it fires on every
successful fetch regardless of `refresh`. Two side effects are deliberate:
queueing *after* the write makes `populate_pim_relations_task`'s own
`get_pim_data(pim_id)` call (`tasks.py:207`, non-refresh; that task runs
`atomic=True` via `execute_locked_task`, the default — see [[core]]) a cache
hit rather than a second live fetch inside the task's own transaction; and
the 404 (`_note_pim_404`)/transient-error branches now queue nothing, rather
than burn the 10-minute `_PIM_POPULATE_QUEUED_TTL` dedup flag on a task that
would just find `data is None` and return 0. **Still open, not touched by
this fix:** a non-refresh *cache hit* never queues population — pre-existing,
but means an already-cached `pim_id` gets no trigger until the key expires.
`populate_pim_relations_task`'s docstring (`tasks.py:203`) and the
`_PIM_POPULATE_QUEUED_TTL` comment (`utils.py:162`) both still say "cache
miss" — stale against this move, don't trust either when tracing the
trigger. `GetPimDataQueuesPopulationTests` (`tests.py:259`) covers all four
branches (miss, refresh success, warm-cache-for-the-task, 404), asserting
the queue only inside `self.captureOnCommitCallbacks(execute=True)` — same
pattern as `QueuePimPopulationDispatchTests` (`tests.py:233`): `LOCMEM_CACHE`
override + `cache.clear()` in `setUp`.

## `get_file_url`'s return line has an operator-precedence bug (`utils.py:361`)

`return "https://" + data.get(f'{size}ThumbnailUrl') or data.get('url') or
data.get('downloadUrl')` — `+` binds tighter than `or`, parsing as
`("https://" + X) or Y or Z`: the `url`/`downloadUrl` fallbacks are dead code,
and a missing `{size}ThumbnailUrl` (`X is None`) raises an uncaught
`TypeError` — the `try/except` (`utils.py:355-360`) closes before this line.
Both call sites, `views.py:198` and `render_pim_photo`
(`tables.py:233-244`), expect a clean `None`/URL — a missing thumbnail 500s
the table instead of falling back to `—`. Bug, not yet fixed; not this
keeper's fix to make.

## `MainProductFilter` — `.order_by()` bleeding into `GROUP BY`

`search_method` (`filters.py:194-200`) ends on `.order_by("-rank")`. Django
folds an explicit `order_by()` column into `GROUP BY` once something
downstream calls `.values(...).annotate(...)` on the same queryset — no
longer hypothetical: `MainProductTableView.get_table_data`
(`views.py:170-171`) works around exactly this with a bare `.order_by()`
before `.values('pk')`, naming `search_method` in its own comment.
`MainProductFilter.search_rank` (`filters.py:181-192`) is a separate
`@staticmethod` for the same reason — `get_table_data` rebuilds the queryset
via `filter(pk__in=...)`, dropping `rank`, and re-applies `search_rank`
afterward (`views.py:180-183`) so group ordering by relevance still works.
Same family: `categories_method` (`filters.py:207-214`) ends on `.distinct()`
for the same M2M-join-duplicates-rows reason; `CategoryFilter` mirrors it
with `Count(F('mainproducts'), distinct=True)`
(`supplier_manager/filters.py:20`) instead of a plain `Count`.

## `_search_pim_id` docstring does not match its code

The docstring (`utils.py:166-177`) promises a search of `ContributorProduct`
"by priceManagerId, then by sku/number", reading `masterRecordId` to reach the
merged `Product`. The code (`utils.py:182-189`) does neither: a single-element
`searches` list — `Where(attribute='number', type='like', value=product.sku)`
— queried straight against `EntityList(name='Product', ...)`. No
`ContributorProduct` step, no `masterRecordId`, no `priceManagerId` fallback
— verified by reading both, not inferred.

Consequence: `sku` is nullable (`models.py:50-53`), so a `MainProduct` with no
`sku` can **never** resolve a `pim_id` through this path — a firmer
explanation for stuck-NULL `pim_id`s than the backlog and the 4h no-match
cache (`_PIM_NO_MATCH_TTL`, `utils.py:161`) alone.

## The 11 Celery tasks

All 11 `@shared_task`s in `tasks.py` go through `execute_locked_task` — the
best-behaved app in the repo on that convention. `reindex_pim_ids` and
`reindex_pim_ids_batch` (`tasks.py:166`, `:187`) set
`time_limit=None, soft_time_limit=None`: a full catalog re-scan outruns any
sane limit. Fan-out: `reindex_pim_ids_task` chunks pks via
`iter_pim_id_pk_batches()` (`utils.py:565`) and queues one
`reindex_pim_ids_batch_task` per chunk to run in parallel; `task_name` is
uniquified per chunk (`tasks.py:190`) or they'd all contend on one Redis lock.
`sync_main_products_task` (`tasks.py:143`) is a 12th function but not a task
itself — no `@shared_task`, just `chain(...)`-ing the 11 into one
`apply_async()` workflow (`tasks.py:144`); each link still goes through
`execute_locked_task` on its own. Easy to confuse: `create_pim_links` only
fills `pim_id__isnull=True`, while `reindex_pim_ids` re-searches PIM for
**every** product (writing only the ones whose value changed), so
`skip_non_empty=True` is what narrows it back to unlinked ones.
`populate_pim_relations_task` (`tasks.py:199-216`) differs from the other 11:
it isn't scheduled or fanned out, it's queued per-`pim_id`, from exactly one
place — `_queue_pim_population` inside `get_pim_data` (see the render-path
section above).

## Price fields and three columns that only look like fields

Seven price fields on `MainProduct` (`models.py:83-117`), ordered tuple
`MP_PRICES` (`models.py:14-22`); `price_list()` (`:142`) returns only the
non-null ones. `kaspi_price` added by
`migrations/0009_mainproduct_kaspi_price.py`. `product_price_manager` writes
these — see [[product_price_manager]]. `MainProductLog` (`models.py:182`) is
the price/stock history row.

`supplier_product_price`, `supplier_product_rrp` and
`supplier_product_discount_price` look like ordinary columns —
`tables.Column` (`tables.py:39-41`), offered in `AVAILABLE_COLUMN_GROUPS`
(`columns.py:36-38`) — but aren't model fields.
`MainProductTableView.get_table_data` (`views.py:146-154`) builds each as a
correlated `Subquery` on `SupplierProduct`, ordered `-updated_at`; that's
ordering a singleton, since `SupplierProduct.main_product` is `unique=True`
(`supplier_product_manager/models.py:24-30`). `grouping.GROUPED_PRICE_COLUMNS`
(`grouping.py:32-40`) deliberately excludes these three — the group head
shows `—` for them (`test_grouping.py:237-251`). `kaspi_price` is a genuine
field but an orphan in the picker: offered at `columns.py:33`, absent from
`MainProductTable.Meta.fields` (`tables.py:100-127`) — selecting it does
nothing.

## `pim_id`: indexed since #155, but the index doesn't make grouping cheap

`migrations/0004_mainproduct_pim_id.py:16` originally added `pim_id` with
`unique=True`; `migrations/0005_mainproduct_categories_m2m.py:32-36` dropped
it. `migrations/0010_alter_mainproduct_pim_id.py` (landed with #155/PR #162)
added `db_index=True` back (`models.py:46-49`) — a plain lookup index,
distinct from the `GinIndex` still only on `search_vector` (`models.py:44`).
**Corrects this file's earlier claim of "no `db_index`" — no longer true.**

Multiplicity — several `MainProduct`s from different suppliers legitimately
share one `pim_id` (it names a verified/merged PIM `Product`, not a
per-supplier `ContributorProduct`) — asserted in `sync_pim_relations`'s
docstring (`utils.py:302-308`), relied on by its plural
`filter(pim_id=...).update(...)` (`:315`) and `_note_pim_404`'s bulk
`update(pim_id=None)` (`:126`), and now also what `grouping.py` collapses
into one head row.

**The index removes a lookup cost, not the grouping cost.**
`MainProductTableView.get_table_data` (`views.py:145-185`) renders one table
per category plus one `categories__isnull=True` bucket (`views.py:160,91-92`),
then computes `Window(partition_by=[F('grp_key')])` (`grouping.py:105-155`)
over that filtered queryset. `grp_key` is
`Coalesce(NullIf(pim_id, ''), Cast('id', TextField()))` (`grouping.py:50-64`)
— an expression, not the indexed column — so the index can't serve this sort;
Postgres sorts every row in the bucket regardless. On a restored production
snapshot (issue #164): 156,016/156,481 `MainProduct`s have no category, the
largest real category holds 67 rows, and all 1,323 duplicated-`pim_id`
groups sit in the uncategorised bucket (aggregate only, per prod-snapshot
rule 3) — the window pass there costs ~70ms -> ~3s (~107MB disk spill)
versus ~+6ms on the 67-row category table; trimming to bare-id columns still
floors ~1.6s. **Benchmark grouping changes against the uncategorised
bucket** — it's effectively the whole catalog, and a category table always
looks fast.

## `render_<column>` is silently skipped when the cell value is empty

Every branching renderer on `MainProductTable` declares `empty_values=()`:
`actions` (`tables.py:33`), `stock_msg` (`:38`), `delivery_days` (`:45`), all
eight `pim_*` columns (`:47-54`). Without it, django-tables2 skips the
renderer and returns the column's `default` whenever the value is `None`/`""`
— a `render_foo` added without `empty_values=()` works for populated rows and
silently renders the table-wide `—` for empty ones, reading like a data
problem, not a wiring one. `GroupHeadRecord` (`grouping.py:207-244`) relies
on the inverse on purpose: `__getattr__` (`:238-241`) returns `None` for any
unset attribute, so an unhandled column falls through to `—` for free — only
the three branching renderers needed an `is_group_head` branch when #155
added the header row.

## `update_stocks` — the two NULLs mean different things

`utils.py:392`, docstring `:393-403`. Two nullable stock columns feed this
and don't carry the same meaning:

- `SupplierProduct.stock` NULL = supplier told us nothing; unknown isn't
  sellable, so `new_stock` coalesces it to `0`.
- `MainProduct.stock` NULL = never synced. Distinct from a synced `0`.

The candidate filter used to coalesce *both* sides to `0`, making `NULL` and
`0` compare equal and silently skipping a never-synced product forever — no
write, no log, uncounted. Fixed by testing the current value's nullness
explicitly: `filter(Q(stock__isnull=True) | ~Q(stock=F('new_stock')))`
(`:414`) — `~Q(stock=F('new_stock'))` alone isn't enough, since SQL's
`NOT (NULL = 0)` is NULL, not true. `UpdateStocksNullSafeTests` (`tests.py:51`)
guards this write path.

**The render-path conflation this used to describe is fixed for two of three
copies.** `render_stock_msg` (`tables.py:166-186`) now branches on
`record.stock is None` before zero/nonzero and returns `NO_STOCK_DATA`
(`:170-172,180-181`); `StockSelectionTests` (`test_grouping.py:270-349`) now
guards it — this file's old claim that no renderer had test coverage is
stale, corrected here. `Supplier.get_delivery_days_for_stock`
(`supplier_manager/models.py:109-122`) also branches on `stock is None`
explicitly, though it still returns the same value as the zero case — now a
documented, deliberate default, not a silent conflation. Unfixed:
`core/templates/shopping_tab/includes/stock_badge.html:2,4` still tests
truthy `product.stock` — see [[core]]; named here, not owned here.
