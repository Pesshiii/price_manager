# supplier_manager

The reference-data app: who supplies, in what currency, with which discount
groups. Small, but nearly everything else imports `Supplier`.

## Models (`supplier_manager/models.py`)

- **`Currency:15`** — `name` + `value`, where `value` is the rate **in tenge**
  (`verbose_name='Тенге'`). Prices elsewhere are converted through this.
- **`Supplier:32`** — the hub. Beyond `name`/`currency`/`pim_id`:
  - `sku_type` + `sku_value` — a **prefix or suffix** applied to build the SKU.
    The builder is `compute_supplier_sku(article, supplier)` in
    `main_product_manager/utils.py:392`, not here.
  - `delivery_days_available` / `delivery_days_navailable`, selected by
    `get_delivery_days_for_stock(stock)` (`:97`).
  - `msg_available` / `msg_navailable` — customer-facing stock strings.
  - `price_update_rate` / `stock_update_rate` + `price_updated_at` /
    `stock_updated_at`.
- **`Discount:103`** — a named discount group belonging to a supplier.
  [[product_price_manager]] matches rules against these.

## Retired in Phase 2b-3: `Category`, `Manufacturer`, `ManufacturerDict`

The supplier-side catalog is gone (migration `0011`). Categories are
[[product]]'s `Category` (a PIM mirror, D2), brands [[product]]'s `Brand` (PIM
only, D1/D3). Things worth knowing if you meet them in old code or data:

- **Migration `0011` declares its dependencies on the three 2b-2 migrations
  that removed every FK/M2M into these models.** The autodetector can't see
  that link, and an empty database migrates in any order — only a populated
  one fails. Keep that pattern for any future model deletion.
- **`0011` exported `ManufacturerDict` to `media/exports/manufacturer_aliases.csv`
  before dropping it** — on production the table was empty, so there is no
  file there.
- **PIM brands do have duplicate spellings** (R5, 2026-09-21: 14 case-only
  groups like STAYER/Stayer of 321). They are separate PIM entities, merged in
  PIM — deliberately not normalised here (D3).
- The «Обновить» chain lost `rebuild_categories`, and beat lost
  `sync-categories`; queued messages for either are rejected once as
  `NotRegistered` after deploy.

## Note

There is a *separate, retiring* `supplier` app — similarly named, not this
one. This app is the live one for suppliers; categories and brands are
[[product]]'s. See [[retiring_stack]].
