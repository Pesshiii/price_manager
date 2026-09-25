---
title: Retired in Phase 2b-3
summary: Category, Manufacturer and ManufacturerDict: what went where.
code: price_manager/supplier_manager/migrations/0011_retire_category_and_manufacturer.py
---
# Retired in Phase 2b-3: `Category`, `Manufacturer`, `ManufacturerDict`

The supplier-side catalog is gone (migration `0011`). Categories are
[[product]]'s `Category` (a PIM mirror, D2), brands [[product]]'s `Brand` (PIM
only, D1/D3). `views.py`/`tables.py`/`admin.py` have no trace of them any
more — only `Supplier`/`Currency`/`Discount` screens remain (see
[[supplier_manager/models-and-list]]). Things worth knowing if you meet the
old models in history or data:

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
