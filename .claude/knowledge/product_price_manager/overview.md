---
title: product_price_manager — overview
summary: The markup engine, its blast radius, and what to know before touching it.
code: price_manager/product_price_manager/
---
# product_price_manager — overview

The markup engine: takes a source price, applies a rule, writes a destination
price onto `MainProduct` (cross-app imports per CLAUDE.md's *Key cross-app
dependencies*). Changes here have the widest blast radius per line in the
repo — `save()`/`apply()`/`delete()`/`deprecate()` on `PriceManager` all
rewrite product data catalog-wide, not just the rule row.

## When touching this app

`PriceTag` is denormalised on purpose. Before "fixing" the duplication between
`PriceManager` and `PriceTag` fields, understand that the copy is the audit
trail. See [[main_product_manager]] for the dest price fields and
[[supplier_product_manager]] for `SP_PRICES`.

Test suite trap: any test that creates two `SupplierProduct` rows against one
`MainProduct` to exercise "minimum across rows" behaviour will fail with
`IntegrityError` on the unique constraint, not with a wrong price — the
constraint fires before any pricing code runs.

Line numbers throughout this file drift with every edit to `models.py` (the
whole file shifted ~9-13 lines since the last audit, 2026-09-22) — treat them
as approximate and re-grep before quoting one in an answer.
