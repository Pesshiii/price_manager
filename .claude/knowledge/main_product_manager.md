# main_product_manager

`MainProduct` — the canonical product record. Highest-churn app in the repo
(171 of the last 200 commits touched it). Owns the PIM integration.

## The trap that costs the most: `.save()` can be an HTTP request

`MainProduct._build_searchvector()` (`main_product_manager/models.py:134`) calls
the external PIM API from inside a model method:

- `_resolve_pim_id(self)` when `pim_id` is unset (`utils.py:184`)
- then `get_pim_data(self.pim_id)` (`utils.py:122`)

Anything that rebuilds search vectors row by row makes **one network round-trip
per row**. When reviewing a loop over `MainProduct`, trace whether it reaches
`rebuild_search_vector()` (`models.py:157`); if it does, that is the finding
regardless of how the queryset was built.

`MainProduct.save()` (`models.py:163`) is a bare `super().save()` — it does
*not* rebuild the vector. The rebuild is always explicit. Don't "fix" the
override by adding a rebuild call into it; that would turn every save in the
codebase into a PIM call.

## PIM scans run with `atomic=False` — moving the write is not enough

`execute_locked_task` wraps its runner in a transaction *by default*, so a task
that calls PIM inside the runner holds one open across the network.

There used to be a comment at both scan sites claiming that hoisting the
`bulk_update` out of the API loop kept the transaction from spanning the HTTP
calls. **It does not.** `execute_locked_task` opens the transaction before
calling the runner, so it stays open for the entire loop regardless of where
the write lands. The real fix is `atomic=False` at the call site — see
[[core]]:

- `tasks.py` `create_pim_links_task` → `utils.py` `create_pim_links`
- `tasks.py` `reindex_pim_ids_batch_task` → `utils.py` `reindex_pim_ids_batch`

Both are safe without the transaction because the Redis lock (not the
transaction) provides mutual exclusion, and both are idempotent re-scans:
`create_pim_links` only fills `pim_id__isnull=True`, and `reindex_pim_ids_batch`
only writes when the resolved id differs. A run that dies mid-loop leaves
committed progress the next run continues from — which is what you want, since
`_search_pim_id`'s `pim_no_match:` cache writes escape a rollback anyway.

Do **not** wrap `push_missing_pim_products` in a transaction "to compensate":
it is `_push_pim_products` underneath, which interleaves HTTP, `bulk_update`
and `sleep` per chunk, so a wrap would reintroduce the same defect and would
also break its documented promise that one failing chunk doesn't lose the
others.

New PIM-touching tasks should pass `atomic=False` rather than reshuffling
writes.

## Why the search vector uses `Value()`, not field references

`_build_searchvector` builds `SearchVector(Value(supplier_name), ...)` rather
than `SearchVector('supplier__name')`. The comment at `models.py:140` says why:
`bulk_update()` / `.update()` do not allow joined fields in a SET expression.
If you switch these to field references the update will fail at the DB layer,
not at import time.

Weights: PIM categories/tags/name = A, `sku`/`article` = B, PIM descriptions +
supplier + manufacturer = C, own `description` = D. `config='russian'`
throughout, backed by a `GinIndex` declared in `Meta.indexes` (`models.py:34`).

## The 11 Celery tasks

All in `tasks.py`, all routed through `execute_locked_task` — this app is the
best-behaved one in the repo on that convention. Two of them take
`time_limit=None, soft_time_limit=None` deliberately (`reindex_pim_ids`,
`reindex_pim_ids_batch`, `tasks.py:163` and `:179`) because a full catalog
re-scan outruns any sane limit.

The fan-out pattern is worth knowing: `reindex_pim_ids_task` uses
`iter_pim_id_pk_batches()` (`utils.py:533`) to chunk pks, then queues one
`reindex_pim_ids_batch_task` per chunk so batches run in parallel across
workers. `task_name` for those is uniquified per chunk
(`f"...reindex_pim_ids_batch:{pks[0]}-{pks[-1]}"`, `tasks.py:182`) — otherwise
they would all contend on one Redis lock and all but the first would skip.

`sync_main_products_task` (`tasks.py:143`) is the one that does *not* go through
`execute_locked_task`.

## `create_pim_links` vs `reindex_pim_ids`

Easy to confuse:
- `create_pim_links` only fills `pim_id__isnull=True`.
- `reindex_pim_ids` re-searches PIM for **every** product so relinked/re-merged
  records pick up a new `pim_id`; writes only those whose value changed.
  `skip_non_empty=True` narrows it back to unlinked ones.

## Price fields

Six of them on `MainProduct` (`models.py:73`–`:102`): `prime_cost`,
`wholesale_price`, `basic_price`, `m_price`, `wholesale_price_extra`,
`discount_price`. The ordered tuple is `MP_PRICES`; `price_list()`
(`models.py:127`) returns only the non-null ones with their Russian
`verbose_name`. `product_price_manager` writes these — see
[[product_price_manager]].

`MainProductLog` (`models.py:167`) is the price/stock history row.

## `update_stocks` — the two NULLs mean different things

`utils.py:385`. Two nullable stock columns feed this, and they do not carry
the same meaning:

- `SupplierProduct.stock` NULL = the supplier told us nothing. Unknown is not
  sellable, so `new_stock` coalesces it to `0`.
- `MainProduct.stock` NULL = never synced. Distinct from a synced `0`.

The candidate filter used to coalesce *both* sides to `0`
(`current_stock_safe`), which made `NULL` and `0` compare equal — a product
that had never been synced and whose supplier reported no stock was silently
skipped forever: no write, no `MainProductLog`, not counted in the return
value. Fixed by testing the current value's nullness explicitly:
`filter(Q(stock__isnull=True) | ~Q(stock=F('new_stock')))`. The plain
`~Q(stock=F('new_stock'))` alone is not enough — SQL's `NOT (NULL = 0)` is
NULL, not true, so those rows drop out of the filter either way.

That `isnull` branch is self-limiting: the first run leaves `stock` non-NULL,
so the row stops matching. `test_second_run_is_a_no_op` guards it.

The `for i in range(0, MainProduct.objects.count(), batch_size)` loop above it
never slices anything — `mps` is the full queryset on every pass. It is
harmless only because the update converges (pass two matches nothing), but it
re-runs the whole subquery `ceil(count / 10000)` times.
