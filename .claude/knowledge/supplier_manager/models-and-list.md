---
title: Models and the /supplier/ list
summary: Currency, Supplier (sku, delivery days, stock messages, priorities), Discount; which of the three supplier pages owns what; SupplierList.
code: price_manager/supplier_manager/models.py, price_manager/supplier_manager/views.py
---
# Models and the /supplier/ list

## Models (`supplier_manager/models.py`)

- **`Currency:22`** — `name` + `value` (`:26`), where `value` is the rate **in
  tenge** (`verbose_name='Тенге'`). Prices elsewhere are converted through
  this.
- **`Supplier:39`** — the hub, **not registered in Django admin**
  (`admin.py` registers only `Discount`) — `SupplierForm` edits it, except
  the levels, which only the `/supplier/` cells edit. Beyond `name`/`currency`/`pim_id`:
  - `sku_type` + `sku_value` — a **prefix or suffix** applied to build the SKU.
    The builder is `compute_supplier_sku(article, supplier)` in
    `main_product_manager/utils.py:500`, not here.
  - `delivery_days_available` / `delivery_days_navailable`, selected by
    `get_delivery_days_for_stock(stock)` (`:141`). `stock is None` (never
    synced) is a deliberate third branch, not folded into the zero-stock
    case — both currently return `delivery_days_navailable`, but the branch
    stays separate so a future change to one doesn't silently change the
    other.
  - `msg_available` / `msg_navailable` — customer-facing stock strings.
  - `price_update_days` / `stock_update_days` + `price_updated_at` /
    `stock_updated_at` — the update interval is a plain day count, NULL =
    "not tracked". Migration `0012` replaced the old `*_update_rate` labels
    (`TIME_FREQ`, now gone from `models.py`; a frozen copy lives in the
    migration) with 1/7/21/NULL. `Supplier.update_status(kind)` (`:161`)
    returns `untracked`/`never`/`overdue`/`ok`; `update_badges()` (`:178`)
    wraps both kinds with their tooltip for `supplier/partials/update_badges.html`,
    shown on «Загрузка прайсов» and in the supplier card — **not** on
    `/supplier/` any more (see *Three supplier pages*). The form edits the interval through
    `IntervalField` (`forms.py:31`) as «число + дней/недель»; the unit is
    **not stored** — `IntervalWidget.decompress` (`forms.py:23`) shows any
    multiple of 7 as weeks, so «14 дней» reopens as «2 недель».
  - `price_priority` / `stock_priority` (added in migration `0010`) —
    **levels, not ranks** (migration `0014`, which dropped `0013`'s
    `DEFERRED` unique constraints): several suppliers may share a number,
    gaps are fine, and nothing is renumbered on save, clear or delete. NULL
    means "the common bottom level", not "ignored". Editable **only** inline
    in the `/supplier/` table (`SupplierPriorityUpdate`, route
    `supplier-priority`, answers with the `priority_cell.html` `<td>` alone —
    no OOB neighbours any more). `SupplierForm` left them out on purpose
    (`forms.py:66`): a level means something only next to the other
    suppliers' levels, and saving the form keeps them as they are. `0013`'s
    dense 1…N data was kept as is: N single-supplier levels reproduce the old
    strict order for ranked suppliers (unranked ones used to go by name;
    now they tie). The only consumer is the product export
    (`product/export.py`, see [[product]]): per price level the supplier with
    the lowest non-zero `prime_cost` wins and *every* MP price comes from it
    (a missing one falls to the next by cost on that level, then to lower
    levels); stock takes the max on the first stock level that has one.
    `SupplierProduct` prices (supplier currency) get no main value at all.
- **`Discount:157`** — a named discount group belonging to a supplier
  (unique per `name`+`supplier`). [[product_price_manager]] matches rules
  against these.

## Three supplier pages — who owns what

Split by task and how often it is done, not by entity (2026-10-16):

- **«Загрузка прайсов»** (`supplier-bulk-upload`; the navbar's «Поставщики» is a
  dropdown of it and «Список поставщиков», `core/templates/includes/header.html`) — the
  operator's daily page and the **only** cross-supplier view of freshness:
  who is overdue, upload, confirm or cancel an import. The «ждёт
  подтверждения» notification links here (see [[supplier_product_manager]]).
- **«Поставщики»** (`/supplier/`) — rarely changed, comparative: the levels
  and how well each supplier's ГП rows are priced. No upload button, no
  freshness badges.
- **The card** (`/supplier/<pk>/`) — one supplier: its price-list rows,
  settings, price managers, `SupplierForm` parameters, and its own freshness
  badges in the header. It still opens the confirmation dialog for
  `?import_run=` — notifications made before the move point there and never expire.

Putting freshness or upload back on the list duplicates the upload page;
putting levels back into the form edits a relative number without the
others in sight.

## `/supplier/` list (`SupplierList`, `views.py:51`)

Rendered by hand from `supplier/partials/list_table_partial.html`
(`supplier_manager/templates/supplier/list.html` extends `base.html` and
includes it), not django-tables2 (the unused `SupplierListTable` was
deleted — no trace of it anywhere in the tree). The ГП counts come from one
annotated query; a test pins the query count so it cannot drift back to
N+1. Two counters (#186): «В прайсе» is `sp_total`, the supplier's
`SupplierProduct` rows, and «В ГП» is `total`, its `MainProduct` rows. The
price columns count ГП rows too. **`sp_total` is a separate grouped query**
(`sp_totals`, `views.py:84`), never part of the supplier annotation:
- A second `Count` over another reverse relation in the same GROUP BY
  multiplies each other's rows.
- A correlated `Subquery` annotation is worse. Django puts it into the GROUP BY
  (`GROUP BY id, 19`), so Postgres evaluates it for every joined ГП row before
  grouping. Shipped in #283, it timed out `/supplier/` in production the same
  day (gunicorn killed the worker).

`test_grouped_supplier_query_has_no_subquery` pins it. The price columns come from
`Count('main_products', filter=…)` per price field (`views.py:72`). They are driven by `PRICE_COLUMNS` in `views.py:44`
for both header and cells — they used to be written out separately and had
silently drifted into different orders. Current columns/labels:
`basic_price`/«Базовая цена», `prime_cost`/«Себестоимость», `m_price`/«Цена
ИМ», `wholesale_price`/«Оптовая цена». They measure what price managers
produced, not what was uploaded, so each cell links to the card's
`#pricemanagers` tab (the card activates a tab from the hash). Sorting by a priority always puts
unranked suppliers last (`views.py:117`).
