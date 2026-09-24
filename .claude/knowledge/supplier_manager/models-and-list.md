---
title: Models and the /supplier/ list
summary: Currency, Supplier (sku, delivery days, stock messages, priorities), Discount; SupplierList.
code: price_manager/supplier_manager/models.py, price_manager/supplier_manager/views.py
---
# Models and the /supplier/ list

## Models (`supplier_manager/models.py`)

- **`Currency:11`** — `name` + `value` (`:15`), where `value` is the rate **in
  tenge** (`verbose_name='Тенге'`). Prices elsewhere are converted through
  this.
- **`Supplier:28`** — the hub, **not registered in Django admin**
  (`admin.py` registers only `Discount`) — `SupplierForm` is the sole place
  it's edited. Beyond `name`/`currency`/`pim_id`:
  - `sku_type` + `sku_value` — a **prefix or suffix** applied to build the SKU.
    The builder is `compute_supplier_sku(article, supplier)` in
    `main_product_manager/utils.py:500`, not here.
  - `delivery_days_available` / `delivery_days_navailable`, selected by
    `get_delivery_days_for_stock(stock)` (`:105`). `stock is None` (never
    synced) is a deliberate third branch, not folded into the zero-stock
    case — both currently return `delivery_days_navailable`, but the branch
    stays separate so a future change to one doesn't silently change the
    other.
  - `msg_available` / `msg_navailable` — customer-facing stock strings.
  - `price_update_days` / `stock_update_days` + `price_updated_at` /
    `stock_updated_at` — the update interval is a plain day count, NULL =
    "not tracked". Migration `0012` replaced the old `*_update_rate` labels
    (`TIME_FREQ`, now gone from `models.py`; a frozen copy lives in the
    migration) with 1/7/21/NULL. `Supplier.update_status(kind)` returns
    `untracked`/`never`/`overdue`/`ok` and drives the «Цены»/«Остатки»
    badges on `/supplier/`. The form edits the interval through
    `IntervalField` (`forms.py`) as «число + дней/недель»; the unit is **not
    stored** — `IntervalWidget.decompress` shows any multiple of 7 as weeks,
    so «14 дней» reopens as «2 недель».
  - `price_priority` / `stock_priority` (added in migration `0010`) —
    **levels, not ranks** (migration `0014`, which dropped `0013`'s
    `DEFERRED` unique constraints): several suppliers may share a number,
    gaps are fine, and nothing is renumbered on save, clear or delete. NULL
    means "the common bottom level", not "ignored". Editable in
    `SupplierForm` and inline in the `/supplier/` table
    (`SupplierPriorityUpdate`, route `supplier-priority`, answers with the
    `priority_cell.html` `<td>` alone — no OOB neighbours any more). `0013`'s
    dense 1…N data was kept as is: N single-supplier levels reproduce the old
    strict order for ranked suppliers (unranked ones used to go by name;
    now they tie). The only consumer is the product export
    (`product/export.py`, see [[product]]): per price level the supplier with
    the lowest non-zero `prime_cost` wins and *every* MP price comes from it
    (a missing one falls to the next by cost on that level, then to lower
    levels); stock takes the max on the first stock level that has one.
    `SupplierProduct` prices (supplier currency) get no main value at all.

## `/supplier/` list (`SupplierList`)

Rendered by hand from `supplier/partials/list_table_partial.html`, not
django-tables2 (the unused `SupplierListTable` was deleted). All per-supplier
counts come from one annotated query (`Count('main_products', filter=…)` per
price field); a test pins the query count so it cannot drift back to N+1.
Price columns are driven by `PRICE_COLUMNS` in `views.py` for both header and
cells — they used to be written out separately and had silently drifted into
different orders. Sorting by a priority always puts unranked suppliers last.
- **`Discount:121`** — a named discount group belonging to a supplier
  (unique per `name`+`supplier`). [[product_price_manager]] matches rules
  against these.
