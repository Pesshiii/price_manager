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
  - `price_update_rate` / `stock_update_rate` + `price_updated_at` /
    `stock_updated_at` — rates are keys into module-level `TIME_FREQ`
    (`:3`, `''`/daily/weekly/every-three-weeks); `SupplierList`
    (`views.py:73-76`) uses this to flag a supplier "outdated".
  - `price_priority` / `stock_priority` (added in migration `0010`) —
    nullable, "меньше — выше приоритет, пусто — не проранжирован." They are
    stored, editable in `SupplierForm`, and covered by tests
    (`tests.py:20-49`), but **nothing currently reads them** — no consumer
    in `main_product_manager` or `product_price_manager` yet. Scaffolding
    for a not-yet-built cross-supplier price/stock selection, not dead code
    to remove.
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
