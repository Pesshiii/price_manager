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
cleanly from committed progress after a mid-loop failure (`_search_pim_id`'s
no-match cache writes escape a rollback anyway). Do **not** wrap
`push_missing_pim_products` (`_push_pim_products` underneath — HTTP,
`bulk_update` and `sleep` interleaved per chunk) in a transaction "to
compensate" — that breaks its promise that one failing chunk doesn't lose
the others. New PIM-touching tasks: pass `atomic=False` rather than
reshuffle writes.

## The PIM cache's render-path cost — and why it bites tests too

`get_pim_data` (`utils.py:133`) on a cache miss does **both**: queues async
population (`_queue_pim_population`, `utils.py:141`) and falls through, next
line, to a synchronous `_fetch_pim_product(...)` (`utils.py:142`) — not an
early return, so a cold cache blocks the request on a PIM HTTP round-trip.
`get_file_url` (`utils.py:340`) has the same shape on a miss (`:349`), minus
the queueing.

`prefetch_pim_data` (`utils.py:322`) loops products one at a time, and
`MainProductTableView.get_context_data` (`views.py:186`) calls `get_file_url`
again per entry (`views.py:198`). **Calls dedupe by `pim_id`/file id, not by
row** — `get_pim_data` caches on `pim_product:{pim_id}` (`:136`),
`get_file_url` on `pim_file:{file_id}` (`:344`) — so real cost per cold page
is bounded by distinct `pim_id`s on the page, not row count (the main page
paginates 5 categories at a time, `views.py:89`, each firing its own
`hx-trigger="load"` fetch, `tables_bycat.html:53,82`). `MainProductTable._pim`
still reads `pim_map` by `record.pk` (`tables.py:230-231`).

**Rendering this table in a test makes live PIM HTTP calls unless patched.**
Tests run under `settings.prod` with the placeholder `PIM_TOKEN`/`PIM_HOST`,
so any test rendering `MainProductTable` with a `pim_id`-bearing product hits
the network via the path above. Working recipe (`test_grouping.py:29-30`):
patch `main_product_manager.views.prefetch_pim_data` and
`.maybe_notify_pim_error`. Creating `MainProduct`s is safe — `save()` doesn't
reach PIM — but a test needing a populated `search_vector` should set it
directly with `SearchVector` over local fields (`test_grouping.py:64-68`)
instead of calling `rebuild_search_vector()`.

## `get_file_url`'s return line has an operator-precedence bug (`utils.py:354`)

`return "https://" + data.get(f'{size}ThumbnailUrl') or data.get('url') or
data.get('downloadUrl')` — `+` binds tighter than `or`, parsing as
`("https://" + X) or Y or Z`: the `url`/`downloadUrl` fallbacks are dead code,
and a missing `{size}ThumbnailUrl` (`X is None`) raises an uncaught
`TypeError` — the `try/except` (`utils.py:348-353`) closes before this line.
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

The docstring (`utils.py:159-170`) promises a search of `ContributorProduct`
"by priceManagerId, then by sku/number", reading `masterRecordId` to reach the
merged `Product`. The code (`utils.py:175-182`) does neither: a single-element
`searches` list — `Where(attribute='number', type='like', value=product.sku)`
— queried straight against `EntityList(name='Product', ...)`. No
`ContributorProduct` step, no `masterRecordId`, no `priceManagerId` fallback
— verified by reading both, not inferred.

Consequence: `sku` is nullable (`models.py:50-53`), so a `MainProduct` with no
`sku` can **never** resolve a `pim_id` through this path — a firmer
explanation for stuck-NULL `pim_id`s than the backlog and the 4h no-match
cache (`_PIM_NO_MATCH_TTL`, `utils.py:154`) alone.

## The 11 Celery tasks

All 11 `@shared_task`s in `tasks.py` go through `execute_locked_task` — the
best-behaved app in the repo on that convention. `reindex_pim_ids` and
`reindex_pim_ids_batch` (`tasks.py:166`, `:187`) set
`time_limit=None, soft_time_limit=None`: a full catalog re-scan outruns any
sane limit. Fan-out: `reindex_pim_ids_task` chunks pks via
`iter_pim_id_pk_batches()` (`utils.py:558`) and queues one
`reindex_pim_ids_batch_task` per chunk to run in parallel; `task_name` is
uniquified per chunk (`tasks.py:190`) or they'd all contend on one Redis lock.
`sync_main_products_task` (`tasks.py:138`) is a 12th function but not a task
itself — no `@shared_task`, just a `chain()` of six of the eleven
(`rebuild_categories_task` → `recalculate_vectors_missing_task` →
`update_prices_task` → `update_stocks_task` → `delete_outdated_logs_task` →
`notify_sync_main_products_task`, `tasks.py:139-146`) run via
`apply_async()` (`:147`); each link still goes through `execute_locked_task`
on its own, and log pruning lands as the second-to-last step of every sync,
not just off the beat schedule. Easy to confuse: `create_pim_links` only
fills `pim_id__isnull=True`, while `reindex_pim_ids` re-searches PIM for
**every** product (writing only the ones whose value changed), so
`skip_non_empty=True` is what narrows it back to unlinked ones.

## The beat schedule silently drops one task, and `lock_ttl` isn't a rate limiter

`price_manager/price_manager/settings/celery.py:38-45`'s `CELERY_BEAT_SCHEDULE`
dict has two entries under the identical key `'update-logs'` — the later one
wins, so `main_product_manager.update_logs` is never scheduled, and the
surviving entry gives `delete_outdated_logs` a bare `schedule: 60` where
every sibling uses `*_MINUTES * 60`. Flagged, not fixed here —
deliberately, since it's currently latent: `docker-compose.yml`'s
`celery_worker` runs `celery -A price_manager worker -l info` with no `-B`,
so `CELERY_BEAT_SCHEDULE` is never consulted anywhere in this repo's compose
stack.

**Check before re-fixing:** a fix already exists, unmerged, on
`claude/zealous-jemison-a8c03e` (commit `e6a8440`) — a distinct
`'delete-outdated-logs'` key plus two regression tests in `core/tests.py`.
One reads the source with `ast` rather than `settings.CELERY_BEAT_SCHEDULE`,
because by import time the duplicate is already gone: the dict just has one
fewer entry and every surviving key is unique, so the loss is invisible at
runtime. The other asserts every schedule entry names a registered Celery
task, catching a misspelled name — the second way a task goes quietly idle.

Don't assume `execute_locked_task`'s `lock_ttl` throttles a task's
*frequency* either — see [[core]]: `core/task_runner.py:133-134` deletes the
lock key in a `finally` right after each run, so it's only a crash-recovery
ceiling, not a rate limit.

## Price fields and three columns that only look like fields

Seven price fields on `MainProduct` (`models.py:83-117`), ordered tuple
`MP_PRICES` (`models.py:14-22`); `price_list()` (`:142`) returns only the
non-null ones. `kaspi_price` added by
`migrations/0009_mainproduct_kaspi_price.py`. `product_price_manager` writes
these — see [[product_price_manager]]. `MainProductLog` (`models.py:182`) is
the price/stock history row.

**Three writers feed `MainProductLog`, and the dominant one is not the
name-obvious one.** `utils.update_logs()` (`utils.py:611`) reads like the
writer, but [[product_price_manager]]'s `PriceManager.apply(logs=True)`
(`product_price_manager/models.py:302-308`) and `PriceTag.get_mp()`
(`:426-434`) also insert rows, reached via module-level `update_prices()`
(`:455`) — which has its own beat entry and is a step in the
`sync_main_products_task` chain above. `get_mp()` is reached unconditionally
every run: `update_prices()`'s `get_updated_mps()` helper calls it for every
`PriceTag` with `p_manager__isnull=True` (three separate calls, `:488,493,498`
— manual/orphan tags, as opposed to the `PriceManager.apply()` path for
rule-driven ones). Any change to `MainProductLog` has to account for all
three call sites, not just the one named after the model.

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

## `MainProductLog` pruning: the slice-direction trap (fixed) and its testing traps

`MainProductLog.Meta.ordering = ['-update_time']` (`models.py:208`), and it
has no secondary key. **General lesson: on this model a bare slice inherits
that DESC order** — `[:n]` means newest-`n`, `[n:]` means
everything-but-the-newest-`n`. `delete_outdated_logs_task` used to prune with
`MainProductLog.objects.all()[:100000]`, which resolves to
`ORDER BY update_time DESC LIMIT 100000` — it deleted the **newest** 100k rows
and kept the oldest, inverting the task's purpose. Caught by printing
`str(qs.query)`, not by reading the code. The runner is now
`utils.delete_outdated_logs(keep=100_000)` (`utils.py:648`), which spells the
order out — `order_by('-update_time', '-id')[keep:]` (`utils.py:663`), an
*offset* slice — retention-cap semantics: keep the newest `keep`, delete the
tail. Writing `order_by` explicitly, rather than trusting `Meta.ordering`, is
the convention here now.

**Why a retention cap, not "delete the oldest 100k".** The obvious-looking
alternative, `order_by('update_time')[:100000]`, is wrong here: the guard
threshold and the slice bound are the same number, so a table sitting at
100,001 rows would collapse to a single surviving row, deleting logs written
seconds earlier. That threshold-equals-bound shape is itself the evidence a
retention cap was intended, not an oldest-purge.

**A user-facing reader confirms which end matters.** `MainProductLogList`
(`views.py:321`), routed `<int:pk>/logs` (`urls.py:23`,
`mainproductlog-list`), renders one product's full history via
`MainProductLogTable` (`tables.py:313-326`, `paginate=False`) — pruning
direction is also this page's data, not just table housekeeping.

**Testing trap — backdating `auto_now_add`.** `update_time` is
`auto_now_add=True`, not nullable, with no `default=`. Both `Model.save()`
and `QuerySet.bulk_create()` re-stamp it to `timezone.now()` on insert —
confirmed by the model's own writers, not by reading Django internals:
`utils.update_logs()` (`utils.py:642-643`) and `PriceManager.apply()`
(`product_price_manager/models.py:306-307`) both `bulk_create()`
`MainProductLog` rows without ever setting `update_time`, into a `NOT NULL`
column with no column default — an insert that would fail if `bulk_create()`
skipped the re-stamp. So `create(update_time=...)` and
`bulk_create([MainProductLog(update_time=...)])` both silently discard an
explicit value the same way; only `QuerySet.update()` doesn't re-stamp
(`auto_now_add` fires only on insert). Backdate via
`MainProductLog.objects.filter(pk=...).update(update_time=stamp)`. No other
backdating helper exists in the repo, and `freezegun` isn't in
`requirements.txt` (both grepped). Pattern: `tests.py::DeleteOutdatedLogsTests`
(`tests.py:264-333`).

**Testing trap — a shared `update_time` makes the tie-break untested by
default.** `Meta.ordering` has no secondary key, so if two rows share an
`update_time`, which is "newest" is undefined without `-id`.
`test_ties_on_update_time_are_broken_deterministically` (`tests.py:318-333`)
manufactures exactly that — five rows via `.create()`, then one
`.filter(pk__in=...).update(update_time=stamp)` forcing an identical
timestamp — and asserts the highest `id` (most recently inserted) survives a
`keep=3` prune. Verified empirically: dropping `'-id'` from
`delete_outdated_logs`'s `order_by` makes this test fail. A test backdating
rows individually must give each a distinct `update_time`, or it collapses
into this same tie by accident.

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
docstring (`utils.py:295-301`), relied on by its plural
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
bucket regardless. On a restored production snapshot (aggregates only, per
prod-snapshot rule 3): 156,016 of 156,481 `MainProduct`s have no category,
and all 1,323 duplicated-`pim_id` groups sit in that uncategorised bucket —
the window pass costs single-digit milliseconds on a small category table
but seconds on the ~156k-row uncategorised one, a merge sort spilling
~107MB to disk (`work_mem`, not CPU, is the bottleneck). **Benchmark
grouping changes against the uncategorised bucket** — it is effectively the
whole catalog, and a category table always looks fast.

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

`utils.py:385`, docstring `:386-396`. Two nullable stock columns feed this
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
explicitly, though it still returns the same value as the zero case — a
documented, deliberate default, not a silent conflation. Unfixed:
`core/templates/shopping_tab/includes/stock_badge.html:2,4` still tests
truthy `product.stock` — see [[core]]; named here, not owned here.
