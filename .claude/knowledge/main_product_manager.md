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

`execute_locked_task` wraps its runner in a transaction *by default*.
Hoisting `bulk_update` out of the API loop does **not** stop the transaction
spanning the HTTP calls — it opens before the runner is called, so it stays
open for the whole loop regardless of where the write lands. Fix is
`atomic=False` at the call site — see [[core]]:

- `tasks.py` `create_pim_links_task` → `utils.py` `create_pim_links`
- `tasks.py` `reindex_pim_ids_batch_task` → `utils.py` `reindex_pim_ids_batch`

Safe without the transaction because the Redis lock, not the transaction,
provides mutual exclusion, and both are idempotent re-scans that resume
cleanly from committed progress after a mid-loop failure
(`_search_pim_id_result`'s no-match cache writes escape a rollback anyway).
Do **not** wrap `push_missing_pim_products` (`_push_pim_products` underneath
— HTTP, `bulk_update` and `sleep` interleaved per chunk) in a transaction "to
compensate" — that breaks its promise that one failing chunk doesn't lose
the others. New PIM-touching tasks: pass `atomic=False` rather than
reshuffle writes.

## The PIM cache's render-path cost — and why it bites tests too

`get_pim_data` (`utils.py:136`) on a cache miss does **both**: queues async
population (`_queue_pim_population`, `utils.py:144`) and falls through, next
line, to a synchronous `_fetch_pim_product(...)` (`utils.py:145`) — not an
early return, so a cold cache blocks the request on a PIM HTTP round-trip.
`get_file_url` (`utils.py:393`) has the same shape on a miss (`:402`), minus
the queueing.

`prefetch_pim_data` (`utils.py:375`) loops products one at a time, and
`MainProductTableView.get_context_data` (`views.py:186`) then calls
`get_file_url` again per entry (`views.py:198`): up to **2N** PIM calls per
cold page (the main page paginates 5 categories at a time, `views.py:89`,
each firing its own `hx-trigger="load"` fetch, `tables_bycat.html:53,82`).
**But calls dedupe by `pim_id`/file id, not by row** — `get_pim_data` caches
on `pim_product:{pim_id}` (`:136`), `get_file_url` on `pim_file:{file_id}`
(`:344`) — so real cost is bounded by distinct `pim_id`s on the page.
`MainProductTable._pim` still reads `pim_map` by `record.pk`
(`tables.py:230-231`).

**Rendering this table in a test makes live PIM HTTP calls unless patched.**
Tests run under `settings.prod` with the placeholder `PIM_TOKEN`/`PIM_HOST`,
so any test rendering `MainProductTable` with a `pim_id`-bearing product hits
the network via the path above. Working recipe (`test_grouping.py:29-30`):
patch `main_product_manager.views.prefetch_pim_data` and
`.maybe_notify_pim_error`. Creating `MainProduct`s is safe — `save()` doesn't
reach PIM — but a test needing a populated `search_vector` should set it
directly with `SearchVector` over local fields (`test_grouping.py:64-68`)
instead of calling `rebuild_search_vector()`.

## `get_file_url`'s return line has an operator-precedence bug (`utils.py:407`)

`return "https://" + data.get(f'{size}ThumbnailUrl') or data.get('url') or
data.get('downloadUrl')` — `+` binds tighter than `or`, parsing as
`("https://" + X) or Y or Z`: the `url`/`downloadUrl` fallbacks are dead code,
and a missing `{size}ThumbnailUrl` (`X is None`) raises an uncaught
`TypeError` — the `try/except` (`utils.py:401-406`) closes before this line.
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

## `_search_pim_id_result` — an empty search must say *why* it's empty

`_search_pim_id_result(product) -> tuple[str | None, str]` (`utils.py:175`)
is the real entry point; `_search_pim_id` (`utils.py:240`) is now a thin
id-only wrapper kept for `_resolve_pim_id` (`utils.py:249`, called from
`_build_searchvector`/`get_pim_data_for_product`). It fires one `like` on
PIM's `Product.number` against `product.sku` and returns one of five
outcomes (`utils.py:164-168`): `_SEARCH_FOUND`, `_SEARCH_ABSENT`,
`_SEARCH_AMBIGUOUS`, `_SEARCH_ERROR`, `_SEARCH_NO_SKU`.

**The trap this replaced**: before this commit a no-sku product fired an
*unconstrained* `like` on `number` — `Where.get()` drops the `value` key
when it's `None` — and could link to an arbitrary `Product`; and every empty
return collapsed to the same "no match", including a network failure. That
matters because `push_missing_pim_products` (`utils.py:568`) *writes to
PIM* — it creates a `PriceManagerProduct` — so feeding it anything but a
confirmed `_SEARCH_ABSENT` risked creating a duplicate PIM record for a
product that might already be linked (a PIM outage mid-scan used to do this
for every unlinked product the scan touched). Only `_SEARCH_ABSENT` may reach
it now: `create_pim_links` (`utils.py:586`) and `reindex_pim_ids_batch`
(`utils.py:658`) both branch on the outcome, not on `pim_id is None`. Anyone
adding a new caller that writes on a miss must do the same, not just check
for `None`.

**The cost of that correctness, in `create_pim_links` only**: its window is
`filter(pim_id__isnull=True)[:1000]` under `Meta.ordering = ['id']`, so it is
the same lowest-1000 unlinked rows every run, and it used to drain because
every product left the unlinked set — linked, or pushed to PIM and given the
id `_push_pim_products` wrote back. An unsearchable product now does neither,
so it would sit at the head of the window forever, costing a slot and a
`time.sleep(delay)` per run. No-sku rows are therefore excluded from the
queryset itself (`utils.py:587-595`); drop that exclusion if a search that
works without an sku is ever added back. `_SEARCH_AMBIGUOUS` rows have no
such containment — they stay in the window by design, since an ambiguous
match is a data problem someone has to resolve in PIM.

The cache key `pim_no_match:{pk}` stores the outcome string itself, not a
bare flag — deliberately **one** key rather than two, so
`get_pim_data_for_product`'s single `cache.delete` on its 404-recovery path
(`utils.py:277`) still clears everything. TTLs differ by reason:
`_PIM_SEARCH_ERROR_TTL` = 5 min for an error, `_PIM_NO_MATCH_TTL` = 4h for a
confirmed absence or an ambiguous match (`utils.py:157-158`). A legacy bare
`True` under the same key (written by an older revision) is dropped and
re-searched rather than trusted (`utils.py:205-208`).

`create_pim_links` and `reindex_pim_ids_batch` both raise `PimSearchError`
(`utils.py:171`) when any search in the run went unanswered — *after* their
`bulk_update`, so committed progress survives the exception. Worth doing
specifically because `maybe_notify_pim_error` is DEBUG-gated (`utils.py:45`)
and prod runs under `settings.prod`, so `_PIM_LAST_ERROR_KEY` gets written
but never read in prod — `TaskRunHistory` (populated from
`execute_locked_task`'s `except` branch, `core/task_runner.py:112-132`) is
the only durable signal that the run failed. The return must stay a
2-tuple: `_normalize_updated_count` (`core/task_runner.py:14-21`) sums every
numeric element of a returned tuple, so a third "failed" element would
silently inflate `updated_count` instead of surfacing separately.

Consequence for `manage.py run_task`: sync mode calls the task function
directly (`management/commands/run_task.py:81`), so `PimSearchError`
now propagates out of `handle()` — its no-argument form (run every task in
sequence) stops at the first failing task instead of finishing the loop.

Testing: `site` is bound into `utils`'s own namespace at import
(`utils.py:16`), so tests must patch `main_product_manager.utils.site`, not
`main_product_manager.pim_client.site`. Before this commit nothing in the
app stubbed `site.get` at all. `SearchPimIdOutcomeTests` and
`PimScanPushGuardTests` (`tests.py:307`, `:433`) are the pattern to copy —
both run under `@override_settings(CACHES=LOCMEM_CACHE)`, needed because the
outcome cache has to be visible to in-process assertions, not the worker
container's shared Redis.

## The 11 Celery tasks

All 11 `@shared_task`s in `tasks.py` go through `execute_locked_task` — the
best-behaved app in the repo on that convention. `reindex_pim_ids` and
`reindex_pim_ids_batch` (`tasks.py:166`, `:187`) set
`time_limit=None, soft_time_limit=None`: a full catalog re-scan outruns any
sane limit. Fan-out: `reindex_pim_ids_task` chunks pks via
`iter_pim_id_pk_batches()` (`utils.py:641`) and queues one
`reindex_pim_ids_batch_task` per chunk to run in parallel; `task_name` is
uniquified per chunk (`tasks.py:190`) or they'd all contend on one Redis lock.
`sync_main_products_task` (`tasks.py:143`) is a 12th function but not a task
itself — no `@shared_task`, just `chain(...)`-ing the 11 into one
`apply_async()` workflow (`tasks.py:144`); each link still goes through
`execute_locked_task` on its own. Easy to confuse: `create_pim_links` only
fills `pim_id__isnull=True`, while `reindex_pim_ids` re-searches PIM for
**every** product (writing only the ones whose value changed), so
`skip_non_empty=True` is what narrows it back to unlinked ones.

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
docstring (`utils.py:348-354`), relied on by its plural
`filter(pim_id=...).update(...)` (`:308`) and `_note_pim_404`'s bulk
`update(pim_id=None)` (`:126`), and now also what `grouping.py` collapses
into one head row.

**The index removes a lookup cost, not the grouping cost.**
`MainProductTableView.get_table_data` (`views.py:145-185`) renders one table
per category plus one for `categories__isnull=True` (the `else` branch at
`views.py:160`; the main page decides whether to show that bucket at
`views.py:91-92`), then computes `Window(partition_by=[F('grp_key')])`
(`grouping.py:105-155`) over that filtered per-bucket queryset. The `pim_id`
index can't serve this sort at all: `grp_key` is
`Coalesce(NullIf(pim_id, ''), Cast('id', TextField()))` (`grouping.py:50-64`)
— an expression, not the indexed column — so Postgres sorts every row in the
bucket regardless. On a restored production snapshot: 156,016 of 156,481
`MainProduct`s have no category, the largest real category holds 67 rows,
and all 1,323 duplicated-`pim_id` groups sit in the uncategorised bucket
(aggregates/counts only, per prod-snapshot rule 3). The window pass costs
~+6ms on a ~67-row category table versus ~70ms -> ~3s on the ~156k-row
uncategorised one (merge sort spilling ~107MB to disk); trimming to bare-id
columns still floors ~1.6s — the partition sort over the whole bucket, not
the `pim_id` lookup, is what's expensive. **Benchmark grouping changes
against the uncategorised bucket** — it is effectively the whole catalog,
and a category table always looks fast.

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

`utils.py:438`, docstring `:439-449`. Two nullable stock columns feed this
and don't carry the same meaning:

- `SupplierProduct.stock` NULL = supplier told us nothing; unknown isn't
  sellable, so `new_stock` coalesces it to `0`.
- `MainProduct.stock` NULL = never synced. Distinct from a synced `0`.

The candidate filter used to coalesce *both* sides to `0`, making `NULL` and
`0` compare equal and silently skipping a never-synced product forever — no
write, no log, uncounted. Fixed by testing the current value's nullness
explicitly: `filter(Q(stock__isnull=True) | ~Q(stock=F('new_stock')))`
(`:407`) — `~Q(stock=F('new_stock'))` alone isn't enough, since SQL's
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
