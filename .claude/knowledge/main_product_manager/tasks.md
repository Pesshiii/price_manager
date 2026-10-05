---
title: Tasks — sync_main_products and update_stocks
summary: The task without @shared_task, update_stocks' NULL vs 0, which rows it skips (set rows, rows with no SupplierProduct) and the post_delete signal that closes the gap, and its batching trap.
code: price_manager/main_product_manager/tasks.py, price_manager/main_product_manager/utils.py, price_manager/supplier_product_manager/models.py
---
# Tasks — sync_main_products and update_stocks

## `sync_main_products_task` has no `@shared_task` (`tasks.py:120-127`)

Plain function `chain()`ing **four** tasks into one `apply_async()` — «Обновить»
on `/products/`: `update_prices_task`, `update_stocks_task`,
`delete_outdated_logs_task`, `notify_sync_main_products_task` (each passes
its `stats` payload along via `_append_step`). `recalculate_vectors_missing`
and `rebuild_categories` are gone from the whole repo now, not just this
chain. `reindex_pim_ids` is a **separate** scheduled task, not part of this
chain. `reindex_pim_ids_batch_task` uniquifies `task_name` per chunk
(`tasks.py:169`) so batches don't contend on one Redis lock.

## `update_stocks` — NULL vs `0`, and its batching trap (`utils.py:496-553`)

Tests `stock__isnull` separately rather than coalescing both sides —
coalescing would compare NULL=0 as equal and never update never-synced
products. Batches over a `pks = list(...values_list('pk', ...))` snapshot
rather than `range(0, count(), batch_size)`: `MainProduct.pk` is a
never-reset `BigAutoField`, so one deleted row makes an offset-derived range
stop short and silently skip the tail. `timezone.now()` read once above the
loop so one run stamps one `stock_updated_at`. Same gap-safe idiom as
`iter_unpushed_product_pk_batches`.

## Which rows it skips (`utils.py:542-543`)

- **Set rows** (`supplier` NULL): stock is recounted afterwards by
  `sync_set_stocks`, called at the end of `update_stocks`.
- **Any row with no `SupplierProduct` at all**, for every supplier
  (`Exists(SupplierProduct main_product=pk)`): such a row is hand-made — the
  «Строка ГП» modal, admin, admin import, a retired set row, «Свой склад»
  returns/bonuses — and its stock was typed in, so there is nothing to sync
  from. Not to be confused with a row whose `SupplierProduct.stock` is NULL
  (it vanished from the file): that still coalesces to 0 — the price list
  speaks and says "unknown".
- `MainProduct.has_supplier_price_list` (`models.py:139`) is the same test:
  `supplier_id` set and `supplierproducts.exists()`.

### The trap this creates, and its closure

`SupplierProduct.main_product` is `SET_NULL`, so a real supplier's row whose
price row is deleted would keep its stale stock forever: it now has no
`SupplierProduct`, so `update_stocks` skips it. The `post_delete` receiver
`zero_stock_of_unsourced_row` (`supplier_product_manager/models.py:219-237`)
zeroes the linked row's stock at once and writes a `MainProductLog` (only if
stock was not already 0). It fires for view, admin and cascade deletes.

**Migrations delete through historical models, so the signal does not fire
there** — deliberately: that is how `product_price_manager/0010_own_stock`
removes the synthetic «Свой склад» price rows (made by `0009`, and by the
now-deleted `supplier_product_manager/unsupplied.py`) without zeroing the
stock of the rows they belonged to. Likewise, any `QuerySet._raw_delete` or
other signal-bypassing delete leaves stale stock behind.
