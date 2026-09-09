# main_product_manager

`MainProduct` — the canonical product record. Highest-churn app in the repo
(171 of the last 200 commits touched it). Owns the PIM integration.

## The trap that costs the most: `.save()` can be an HTTP request

`MainProduct._build_searchvector()` (`main_product_manager/models.py:148`) calls
the external PIM API from inside a model method:

- `_resolve_pim_id(self)` when `pim_id` is unset (`utils.py:195`)
- then `get_pim_data(self.pim_id)` (`utils.py:133`)

Anything that rebuilds search vectors row by row makes **one network round-trip
per row**. When reviewing a loop over `MainProduct`, trace whether it reaches
`rebuild_search_vector()` (`models.py:171`); if it does, that is the finding
regardless of how the queryset was built.

`MainProduct.save()` (`models.py:177`) is a bare `super().save()` — it does
*not* rebuild the vector, always explicit. Don't "fix" the override by adding
a rebuild call into it; that would turn every save in the codebase into a PIM
call.

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
compensate" — that reintroduces the defect and breaks its promise that one
failing chunk doesn't lose the others. New PIM-touching tasks: pass
`atomic=False` rather than reshuffle writes.

## The PIM cache's render-path cost

`get_pim_data` (`utils.py:133`) on a cache miss does **both**: queues async
population via `_queue_pim_population` (`utils.py:141`) and then falls
through, on the next line, to a synchronous `_fetch_pim_product(...)`
(`utils.py:142`) — not an early return. A cold cache means a blocking PIM
HTTP round-trip inline in the request. `get_file_url` (`utils.py:340`) has
the same shape on a miss (`utils.py:349`), minus the queueing.

`prefetch_pim_data` (`utils.py:322`) loops products one at a time — no
`cache.get_many` — and `MainProductTableView.get_context_data`
(`views.py:159`) then calls `get_file_url` again per entry
(`views.py:169-171`): up to **2N** PIM calls per cold table page. The main
page paginates 5 categories per page (`views.py:86`), each firing its own
`hx-trigger="load"` table fetch (`tables_bycat.html:53,82`) — a cold main
page runs several 2N-call loads concurrently. Row pagination itself is a
separate number — the library default of 25, since no `paginate_by`/
`per_page`/`table_pagination` is set anywhere in this app or `core` (grep,
zero matches) — don't confuse it with the categories' 5.

**But those calls are deduplicated by `pim_id`, not by row.** `get_pim_data`
caches on `f"pim_product:{pim_id}"` (`utils.py:136`), `get_file_url` on
`f"pim_file:{file_id}"` (`utils.py:344`) — keyed on PIM identity, not
`MainProduct.pk`. `MainProduct`s sharing one `pim_id` (see schema-history
below) collapse to one HTTP call at the cache layer, so a cold table's real
cost is bounded by *distinct* `pim_id`s on the page, not row count — worth
knowing before "optimising" `pim_map` to key on `pim_id` instead of `pk`; the
dedup already happens one layer down. `tables.py` reads `pim_map` by
`record.pk` (`tables.py:147`) — a regroup-by-`pim_id` would have to move
that keying.

**`get_file_url`'s return line has an operator-precedence bug** (`utils.py:354`):
`return "https://" + data.get(f'{size}ThumbnailUrl') or data.get('url') or
data.get('downloadUrl')` — `+` binds tighter than `or`, so this parses as
`("https://" + X) or Y or Z`. The `url`/`downloadUrl` fallbacks are dead code
(any non-empty `X` returns via the first branch; `X == ""` still returns the
truthy `"https://"`), and a file record missing `{size}ThumbnailUrl` (`X is
None`) raises `TypeError: can only concatenate str ... to str` — uncaught,
since the `try/except` above (`utils.py:348-353`) closes *before* this line
and only guards `site.get`/`cache.set`. That propagates to both call sites,
`views.py:171` and `render_pim_photo` (`tables.py:154`), neither of which
expects an exception — a missing thumbnail 500s the table fetch instead of
falling back to the `—` placeholder `render_pim_photo` was written to
produce. Bug, not yet fixed; this app's keeper doesn't own the fix.

## Why the search vector uses `Value()`, not field references

`_build_searchvector` builds `SearchVector(Value(supplier_name), ...)` rather
than `SearchVector('supplier__name')` because `bulk_update()` / `.update()`
don't allow joined fields in a SET expression (`models.py:154-155`) — switch
to field references and the update fails at the DB layer, not import time.
Weights: PIM categories/tags/name = A, `sku`/`article` = B, PIM descriptions +
supplier + manufacturer = C, own `description` = D. `config='russian'`
throughout, `GinIndex` in `Meta.indexes` (`models.py:44`).

## `MainProductFilter` — `.order_by()` bleeding into `GROUP BY`

`search_method` (`filters.py:181-187`) ends on `.order_by("-rank")`. Django
folds a column from an explicit `order_by()` into `GROUP BY` once something
downstream calls `.values(...).annotate(...)` on the same queryset, so
(high-confidence, not run against a live plan)
`MainProductFilter(request.GET).qs.values('pim_id').annotate(count=Count('pk'))`
would yield one row per `(pim_id, rank)` instead of one per `pim_id` — **only
with a search term present**. Fix: a bare `.order_by()` before `.values()`.
Distinct from the old `Meta.ordering`-into-`GROUP BY` bug fixed in Django 3.1
— `Meta.ordering = ['id']` here (`models.py:42`) doesn't trigger that one.

Same family: `categories_method` (`filters.py:194-201`) ends on `.distinct()`
because the categories M2M join duplicates rows — why `CategoryFilter` uses
`Count(F('mainproducts'), distinct=True)` (`supplier_manager/filters.py:20`)
instead of a plain `Count`; any new per-group count needs the same while that
join is on the queryset. See [[supplier_manager]]. No `Window`, `FirstValue`
or `RowNumber` usage exists anywhere in the repo — work that needs one (e.g.
picking one row per `pim_id`) has no local precedent to copy.

## `_search_pim_id` docstring does not match its code

The docstring (`utils.py:159-170`) promises a search of `ContributorProduct`
"by priceManagerId, then by sku/number", reading `masterRecordId` to reach the
merged `Product`. The code (`utils.py:175-182`) does neither: a single-element
`searches` list — `Where(attribute='number', type='like', value=product.sku)`
— queried straight against `EntityList(name='Product', ...)`. No
`ContributorProduct` step, no `masterRecordId`, no `priceManagerId` fallback
— verified by reading both, not inferred.

Consequence: `sku` is nullable (`models.py:49-52`), so a `MainProduct` with no
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
`sync_main_products_task` (`tasks.py:143`) is a 12th function but not a task
itself — no `@shared_task`, just `chain(...)`-ing the 11 into one
`apply_async()` workflow (`tasks.py:144`); each link still goes through
`execute_locked_task` on its own.

Easy to confuse: `create_pim_links` only fills `pim_id__isnull=True`, while
`reindex_pim_ids` re-searches PIM for **every** product (writing only the
ones whose value changed) so relinked/re-merged records pick up a new
`pim_id`; `skip_non_empty=True` narrows it back to unlinked ones.

## Price fields

Seven of them on `MainProduct` (`models.py:82-116`): `prime_cost`,
`wholesale_price`, `basic_price`, `m_price`, `wholesale_price_extra`,
`kaspi_price` (added by `migrations/0009_mainproduct_kaspi_price.py`),
`discount_price`. Ordered tuple `MP_PRICES` (`models.py:14-22`);
`price_list()` (`models.py:141`) returns only the non-null ones with Russian
`verbose_name`. `product_price_manager` writes these — see
[[product_price_manager]]. `MainProductLog` (`models.py:181`) is the
price/stock history row.

## Three table columns are per-request `Subquery` annotations, not fields

`supplier_product_price`, `supplier_product_rrp` and
`supplier_product_discount_price` look like ordinary columns — `tables.Column`
(`tables.py:28-30`), offered in `AVAILABLE_COLUMN_GROUPS` (`columns.py:36-38`)
right alongside real `MainProduct` price fields — but aren't model fields.
`MainProductTableView.get_table_data` (`views.py:140-155`) builds each as a
correlated `Subquery`:
`SupplierProduct.objects.filter(main_product=OuterRef('pk')).order_by('-updated_at').values(...)[:1]`.
Nothing at the column-declaration layer reveals the difference, so any
queryset-level work over "the price columns" must special-case these three.
The `.order_by('-updated_at')[:1]` isn't choosing a "best" supplier —
`SupplierProduct.main_product` is `unique=True`
(`supplier_product_manager/models.py:24-30`), so the source set already has
at most one row per `MainProduct`; it's ordering a singleton.

`kaspi_price` is a genuine `MainProduct` field (see Price fields) but is an
orphan in the picker: offered at `columns.py:33`, absent from
`MainProductTable.Meta.fields` (`tables.py:85-112`) — selecting it does
nothing at all.

## `pim_id` schema history explains "many `MainProduct`s, one `pim_id`"

`migrations/0004_mainproduct_pim_id.py:16` originally added `pim_id` with
`unique=True`; `migrations/0005_mainproduct_categories_m2m.py:32-36` dropped
it. Today it's a plain nullable `CharField` (`models.py:46-48`) with **no
`db_index`** — `Meta.indexes` declares only the `GinIndex` on `search_vector`
(`models.py:44`), so any grouping or lookup by `pim_id` is an unindexed scan.

The multiplicity — several `MainProduct`s (from different suppliers)
legitimately sharing one `pim_id`, since it points at a verified/merged PIM
`Product` rather than a per-supplier `ContributorProduct` — is asserted in
`sync_pim_relations`'s docstring (`utils.py:295-301`) and relied on by its
plural `filter(pim_id=...).update(...)` (`utils.py:308`) and by
`_note_pim_404`'s bulk `update(pim_id=None)` (`utils.py:126`).

## `update_stocks` — the two NULLs mean different things

`utils.py:385`, docstring `utils.py:386-396`. Two nullable stock columns feed
this and don't carry the same meaning:

- `SupplierProduct.stock` NULL = supplier told us nothing; unknown isn't
  sellable, so `new_stock` coalesces it to `0`.
- `MainProduct.stock` NULL = never synced. Distinct from a synced `0`.

The candidate filter used to coalesce *both* sides to `0`, making `NULL` and
`0` compare equal — a never-synced product whose supplier reported no stock
was silently skipped forever: no write, no `MainProductLog`, uncounted.
Fixed by testing the current value's nullness explicitly:
`filter(Q(stock__isnull=True) | ~Q(stock=F('new_stock')))` (`utils.py:407`)
— `~Q(stock=F('new_stock'))` alone isn't enough, since SQL's
`NOT (NULL = 0)` is NULL, not true. `UpdateStocksNullSafeTests`
(`tests.py:51`) guards this write path.

**The rule holds only on the write path — the table renderers violate it.**
`render_stock_msg` (`tables.py:117-123`) does `if not record.stock or
record.stock == 0: return record.supplier.msg_navailable` — a never-synced
(`NULL`) product renders identically to a genuinely-zero one, the exact
conflation `update_stocks` was fixed to avoid. `Supplier
.get_delivery_days_for_stock` (`supplier_manager/models.py:97-100`) has the
same `if stock and stock > 0` shape; its only caller in the repo is
`tables.py:128`. A third, independent copy lives in the cart feature —
`core/templates/shopping_tab/includes/stock_badge.html:2-8` branches on
`{% if product.stock %}` — see [[core]] (record this one via `core-keeper`
too; this file can name it but doesn't own it). No test guards any of the
three renderers the way `UpdateStocksNullSafeTests` guards the write path.
