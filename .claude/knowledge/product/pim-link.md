---
title: Product.pim_id is a PriceManagerProduct id
summary: What pim_id identifies since PR #184 and the consequences for local Products.
code: price_manager/product/models.py
---
# Product.pim_id is a PriceManagerProduct id

## `Product.pim_id` now names a PIM `PriceManagerProduct` (PMP), not a PIM `Product`

Before this branch, `pim_id` was the id of a PIM `Product`. Now it's the id of
a PIM **`PriceManagerProduct`** — a through record whose `platformID` is our
`Product.pk` and whose `productId` points at the PIM `Product`. The full link
chain, who pushes it (`reindex_pim_ids`), and the two-hop read path are owned
by [[main_product_manager]] — don't restate them here. Product-owned
consequences:

- `pim_id` stays `NULL` on a `Product` until that reindex pushes its PMP. A
  fresh `Product` with no `pim_id` is normal, not broken
  (`test_products_without_pim_id_coexist`).
- Most `Product` rows today are created **locally**, not by PIM sync or by a
  seed migration: `main_product_manager.utils.link_unlinked_main_products`
  creates `Product(number=sku, name=<that MainProduct's name>)` with `pim_id`
  left `NULL`. Don't assume a `Product` with data came from
  `sync_product_from_pim` or `0005`'s seed.
- `name` **stopped being unique** (it was, briefly, under `0006`): several
  local `Product`s can point at one PIM `Product` (PIM `Product` hasMany
  `priceManagerProducts`), and PIM's own metadata doesn't declare
  `Product.name`/`Product.number` unique either
  (`test_name_is_not_unique`, `product/tests/test_models.py`).
