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
*not* rebuild the vector. The rebuild is always explicit. Don't "fix" the
override by adding a rebuild call into it; that would turn every save in the
codebase into a PIM call.

## PIM scans run with `atomic=False` — moving the write is not enough

`execute_locked_task` wraps its runner in a transaction *by default*, so a task
that calls PIM inside the runner holds one open across the network.

There used to be a comment at both scan sites claiming that hoisting the
`bulk_update` out of the API loop kept the transaction from spanning the HTTP
calls. **It does not** — `execute_locked_task` opens the transaction before
calling the runner, so it stays open for the whole loop regardless of where
the write lands. The fix is `atomic=False` at the call site — see [[core]]:

- `tasks.py` `create_pim_links_task` → `utils.py` `create_pim_links`
- `tasks.py` `reindex_pim_ids_batch_task` → `utils.py` `reindex_pim_ids_batch`

Both are safe without the transaction because the Redis lock (not the
transaction) provides mutual exclusion, and both are idempotent re-scans:
`create_pim_links` only fills `pim_id__isnull=True`, and `reindex_pim_ids_batch`
only writes when the resolved id differs. A run that dies mid-loop leaves
committed progress the next run continues from — which is what you want, since
`_search_pim_id`'s `pim_no_match:` cache writes escape a rollback anyway.

Do **not** wrap `push_missing_pim_products` in a transaction "to compensate":
it's `_push_pim_products` underneath, interleaving HTTP, `bulk_update` and
`sleep` per chunk — wrapping it would reintroduce the same defect and break
its promise that one failing chunk doesn't lose the others. New PIM-touching
tasks should pass `atomic=False` rather than reshuffling writes.

## The PIM cache's render-path cost

`get_pim_data` (`utils.py:133`) on a cache miss does **both** things: it
queues async population via `_queue_pim_population` (`utils.py:141`) and
then falls through, on the very next line, to a synchronous
`_fetch_pim_product(...)` (`utils.py:142`) — the queue call is not an early
return. A cold cache means a blocking PIM HTTP round-trip inline in the
request. `get_file_url` (`utils.py:340`) has the same blocking shape on a
miss (`site.get(FileRecord(...))`, `utils.py:349`), minus the queueing.

`prefetch_pim_data` (`utils.py:322`) loops products one at a time — no
`cache.get_many`, no batching — and `MainProductTableView.get_context_data`
(`views.py:159`) then calls `get_file_url` again for every entry it gets
back (`views.py:169-171`): up to **2N** PIM calls per cold table page. The
main page paginates 5 categories per page (`Paginator(cat_filter.qs, 5)`,
`views.py:86`), each firing its own `hx-trigger="load"` table fetch
(`tables_bycat.html:53,82`) — so a cold main page runs several of these
2N-call loads concurrently.

`prefetch_pim_data` returns `{product.pk: data}`; `tables.py` reads it by
`record.pk` (`tables.py:147`) — a future regroup-by-`pim_id` has to move
that keying.

## Why the search vector uses `Value()`, not field references

`_build_searchvector` builds `SearchVector(Value(supplier_name), ...)` rather
than `SearchVector('supplier__name')`. The comment at `models.py:154-155` says
why: `bulk_update()` / `.update()` do not allow joined fields in a SET
expression. If you switch these to field references the update will fail at
the DB layer, not at import time.

Weights: PIM categories/tags/name = A, `sku`/`article` = B, PIM descriptions +
supplier + manufacturer = C, own `description` = D. `config='russian'`
throughout, backed by a `GinIndex` declared in `Meta.indexes` (`models.py:44`).

## `MainProductFilter` — `.order_by()` bleeding into `GROUP BY`

`search_method` (`filters.py:181-187`) ends on `.order_by("-rank")` as its
last call — confirmed at the call site. Django folds a column from an
explicit `order_by()` into `GROUP BY` once something downstream calls
`.values(...).annotate(...)` on the same queryset, so (high-confidence, not
run against a live query plan)
`MainProductFilter(request.GET).qs.values('pim_id').annotate(count=Count('pk'))`
would yield one row per `(pim_id, rank)` instead of one per `pim_id` — **only
when a search term is present**, so it looks fine against an empty search.
Fix: a bare `.order_by()` before `.values()`. Distinct from the old
`Meta.ordering`-into-`GROUP BY` bug fixed in Django 3.1 — `Meta.ordering =
['id']` here (`models.py:42`) doesn't trigger that one.

Same family: `categories_method` (`filters.py:194-201`) ends on `.distinct()`
because the categories M2M join duplicates rows — why `CategoryFilter` uses
`Count(F('mainproducts'), distinct=True)` (`supplier_manager/filters.py:20`)
instead of a plain `Count`. Any new per-group count needs the same
`distinct=True` while that join is on the queryset. See [[supplier_manager]].

## `_search_pim_id` docstring does not match its code

The docstring (`utils.py:159-170`) promises a search of `ContributorProduct`
"by priceManagerId, then by sku/number", reading `masterRecordId` to reach
the merged `Product`. The code (`utils.py:175-182`) does neither: a
single-element `searches` list — `Where(attribute='number', type='like',
value=product.sku)` — queried straight against `EntityList(name='Product',
...)`. No `ContributorProduct` step, no `masterRecordId`, no
`priceManagerId` fallback — verified by reading both, not inferred.

Practical consequence: `sku` is nullable (`models.py:49-52`), so a
`MainProduct` with no `sku` can **never** resolve a `pim_id` through this
path — a firmer explanation for stuck-NULL `pim_id`s than the backlog and
the 4h no-match cache (`_PIM_NO_MATCH_TTL`, `utils.py:154`) alone.

## The 11 Celery tasks

All 11 `@shared_task`-decorated functions in `tasks.py` are routed through
`execute_locked_task` — this app is the best-behaved one in the repo on that
convention. Two take `time_limit=None, soft_time_limit=None` deliberately
(`reindex_pim_ids`, `reindex_pim_ids_batch`, `tasks.py:166` and `:187`)
because a full catalog re-scan outruns any sane limit.

The fan-out pattern is worth knowing: `reindex_pim_ids_task` uses
`iter_pim_id_pk_batches()` (`utils.py:558`) to chunk pks, then queues one
`reindex_pim_ids_batch_task` per chunk so batches run in parallel across
workers. `task_name` for those is uniquified per chunk
(`f"...reindex_pim_ids_batch:{pks[0]}-{pks[-1]}"`, `tasks.py:190`) — otherwise
they would all contend on one Redis lock and all but the first would skip.

`sync_main_products_task` (`tasks.py:143`) is a 12th function in the file but
not itself a Celery task: no `@shared_task`, just a plain function that
chains the 11 into one `apply_async()` workflow (`chain(...)`, `tasks.py:144`).
That's the mechanism, not an exception — each task in the chain still goes
through `execute_locked_task` on its own.

## `create_pim_links` vs `reindex_pim_ids`

Easy to confuse:
- `create_pim_links` only fills `pim_id__isnull=True`.
- `reindex_pim_ids` re-searches PIM for **every** product so relinked/re-merged
  records pick up a new `pim_id`; writes only those whose value changed.
  `skip_non_empty=True` narrows it back to unlinked ones.

## Price fields

Seven of them on `MainProduct` (`models.py:82-116`): `prime_cost`,
`wholesale_price`, `basic_price`, `m_price`, `wholesale_price_extra`,
`kaspi_price` (added by `migrations/0009_mainproduct_kaspi_price.py`),
`discount_price`. The ordered tuple `MP_PRICES` (`models.py:14-22`);
`price_list()` (`models.py:141`) returns only the non-null ones with their
Russian `verbose_name`. `product_price_manager` writes these — see
[[product_price_manager]].

`MainProductLog` (`models.py:181`) is the price/stock history row.

## `pim_id` schema history explains "many `MainProduct`s, one `pim_id`"

`migrations/0004_mainproduct_pim_id.py:16` originally added `pim_id` with
`unique=True`; `migrations/0005_mainproduct_categories_m2m.py:32-36` (the
`AlterField` near the end) dropped it. Today it's a plain nullable
`CharField` (`models.py:46-48`) with **no `db_index`** — `Meta.indexes`
declares only the `GinIndex` on `search_vector` (`models.py:44`). Any
grouping or lookup by `pim_id` is therefore an unindexed scan today.

The multiplicity — several `MainProduct`s (from different suppliers)
legitimately sharing one `pim_id`, since it points at a verified/merged PIM
`Product` rather than a per-supplier `ContributorProduct` — is asserted in
`sync_pim_relations`'s docstring (`utils.py:295-301`) and relied on by its
plural `filter(pim_id=...).update(...)` (`utils.py:308`) and by
`_note_pim_404`'s bulk `update(pim_id=None)` (`utils.py:126`).

## `update_stocks` — the two NULLs mean different things

`utils.py:385`, docstring `utils.py:386-396`. Two nullable stock columns feed
this, and they do not carry the same meaning:

- `SupplierProduct.stock` NULL = the supplier told us nothing. Unknown is not
  sellable, so `new_stock` coalesces it to `0`.
- `MainProduct.stock` NULL = never synced. Distinct from a synced `0`.

The candidate filter used to coalesce *both* sides to `0`
(`current_stock_safe`), which made `NULL` and `0` compare equal — a product
that had never been synced and whose supplier reported no stock was silently
skipped forever: no write, no `MainProductLog`, not counted in the return
value. Fixed by testing the current value's nullness explicitly:
`filter(Q(stock__isnull=True) | ~Q(stock=F('new_stock')))` (`utils.py:407`).
The plain `~Q(stock=F('new_stock'))` alone is not enough — SQL's
`NOT (NULL = 0)` is NULL, not true, so those rows drop out of the filter
either way.

That `isnull` branch is self-limiting: the first run leaves `stock` non-NULL,
so the row stops matching. `test_second_run_is_a_no_op` guards it.

The `for i in range(0, MainProduct.objects.count(), batch_size)` loop above it
never slices anything — `mps` is the full queryset on every pass. It is
harmless only because the update converges (pass two matches nothing), but it
re-runs the whole subquery `ceil(count / 10000)` times.
