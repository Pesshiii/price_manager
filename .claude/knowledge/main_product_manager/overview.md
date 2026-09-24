---
title: main_product_manager — overview
summary: MainProduct as the per-supplier stock and price row; how fast this app's notes rot.
code: price_manager/main_product_manager/
---
# main_product_manager — overview

`MainProduct` — the canonical product record: a per-supplier stock+price row
hanging off `product.Product`. Owns the PIM integration. Full audit pass
against current `main` on 2026-09-22: the PMP through-link design (originally
PR #184) is merged, so it's simply how the code reads now. Every line ref
below was re-checked in this pass — most had drifted tens of lines from
docstring/refactor churn. This file rots fast; re-verify before trusting.
