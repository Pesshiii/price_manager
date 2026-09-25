---
title: Tasks — sync_main_products and update_stocks
summary: The task without @shared_task, and update_stocks' NULL vs 0 and batching trap.
code: price_manager/main_product_manager/tasks.py, price_manager/main_product_manager/utils.py
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

## `update_stocks` — NULL vs `0`, and its batching trap (`utils.py:456-498`)

Tests `stock__isnull` separately rather than coalescing both sides —
coalescing would compare NULL=0 as equal and never update never-synced
products. Batches over a `pks = list(...values_list('pk', ...))` snapshot
rather than `range(0, count(), batch_size)`: `MainProduct.pk` is a
never-reset `BigAutoField`, so one deleted row makes an offset-derived range
stop short and silently skip the tail. `timezone.now()` read once above the
loop so one run stamps one `stock_updated_at`. Same gap-safe idiom as
`iter_unpushed_product_pk_batches`.
