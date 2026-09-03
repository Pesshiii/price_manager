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

## `transaction.atomic()` cannot span an HTTP call

`execute_locked_task` wraps its runner in a transaction, so a task that calls
PIM inside the runner holds a DB transaction open across the network. The
established workaround: accumulate objects in the API loop, do the single
`bulk_update` **after** it. Both sites are commented:

- `utils.py:523` (`create_pim_links`)
- `utils.py:573` (`reindex_pim_ids_batch`)

New PIM-touching code should follow that same shape.

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
`iter_pim_id_pk_batches()` (`utils.py:530`) to chunk pks, then queues one
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
