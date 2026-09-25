---
title: product_price_manager — overview
summary: The markup engine, its blast radius, and what to know before touching it.
code: price_manager/product_price_manager/
---
# product_price_manager — overview

The markup engine: takes a source price, applies a rule, writes a destination
price onto `MainProduct` (cross-app imports into [[main_product_manager]] and
[[supplier_product_manager]] — pricing logic bridges them, per CLAUDE.md's
*Key cross-app dependencies*). Changes here have the widest blast radius per
line in the repo — `save()`/`apply()`/`delete()`/`deprecate()` on
`PriceManager` (`models.py:290,315,334,339`) all rewrite product data
catalog-wide, not just the rule row. See
[[product_price_manager/models-and-lifecycle]] for the four methods and
[[product_price_manager/pricing]] for how a fitting product set and its price
are computed.

## When touching this app

`PriceTag` is denormalised on purpose. Before "fixing" the duplication between
`PriceManager` and `PriceTag` fields, understand that the copy is the audit
trail — see [[product_price_manager/models-and-lifecycle]]. See
[[main_product_manager]] for the dest price fields and
[[supplier_product_manager]] for `SP_PRICES`.

Test suite trap: any test that creates two `SupplierProduct` rows against one
`MainProduct` to exercise "minimum across rows" behaviour will fail with
`IntegrityError` on the unique constraint (`main_product` is `unique=True`,
`supplier_product_manager/models.py:24-30`), not with a wrong price — the
constraint fires before any pricing code runs.

Line numbers in this app's topics were re-verified against `models.py` on
2026-09-24; they still drift with every edit — re-grep before quoting one in
an answer rather than trusting it at sight.
