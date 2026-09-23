# supplier_manager

The reference-data app: who supplies, in what currency, with which discount
groups. Small, but nearly everything else imports `Supplier`. Three models
remain (`Currency`, `Supplier`, `Discount`) — see Phase 2b-3 below for what
was removed.

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
    nullable, "меньше — выше приоритет, пусто — не проранжирован." Editable
    in `SupplierForm` and inline in the `/supplier/` table
    (`SupplierPriorityUpdate`, route `supplier-priority`, answers with the
    `priority_cell.html` `<td>`, plus OOB cells for any shifted neighbours).
    **Unique per field** (migration `0013`, `DEFERRED` constraints; NULLs
    unlimited). A taken number is not an error: `Supplier.save()` calls
    `make_room()`, which shifts the contiguous run of taken numbers from the
    target by +1 (a gap stops it). For that to work, `validate_constraints`
    excludes both fields — Django 5.2 checks `UniqueConstraint`s in
    `ModelForm`, and would otherwise reject the number before `save()` runs.
    `queryset.update()` bypasses all of this; the database then catches it at
    commit. Tests must `SET CONSTRAINTS ALL IMMEDIATE` to see a violation —
    `TestCase` never commits. And a `RunPython` that updates this table must
    do the same before an `AddConstraint` in the same migration, or Postgres
    refuses with «pending trigger events» (only on a populated DB). **Nothing
    in business logic reads them yet** — no consumer in
    `main_product_manager` or `product_price_manager`. Scaffolding for a
    not-yet-built cross-supplier price/stock selection, not dead code.

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

## Retired in Phase 2b-3: `Category`, `Manufacturer`, `ManufacturerDict`

The supplier-side catalog is gone (migration `0011`). Categories are
[[product]]'s `Category` (a PIM mirror, D2), brands [[product]]'s `Brand` (PIM
only, D1/D3). `views.py`/`tables.py`/`admin.py` have no trace of them any
more — only `Supplier`/`Currency`/`Discount` screens remain. Things worth
knowing if you meet the old models in history or data:

- **Migration `0011` declares its dependencies on the three 2b-2 migrations
  that removed every FK/M2M into these models** (`main_product_manager.0012`,
  `supplier_product_manager.0010`, `product_price_manager.0004`). The
  autodetector can't see that link, and an empty database migrates in any
  order — only a populated one fails. Keep that pattern for any future model
  deletion.
- **`0011` exported `ManufacturerDict` to `media/exports/manufacturer_aliases.csv`
  before dropping it, but only if the table had rows** — on production it was
  empty, so the export function prints a message and returns without writing
  anything; there is no file there.
- **PIM brands do have duplicate spellings** (R5, 2026-09-21: 14 case-only
  groups like STAYER/Stayer of 321). They are separate PIM entities, merged in
  PIM — deliberately not normalised here (D3).

## Note

There is a *separate, retiring* `supplier` app — similarly named, not this
one. This app is the live one for suppliers; categories and brands are
[[product]]'s. See [[retiring_stack]].
