---
title: Supplier sku and linking to Product
summary: compute_supplier_sku, resolve_product/link_unlinked_main_products (every ГП row gets a Product at once, by sku and brand) and the open question of linking different skus to one Product.
code: price_manager/main_product_manager/utils.py
---
# Supplier sku and linking to Product

## `compute_supplier_sku` — the only thing left tying import to PIM

`compute_supplier_sku(article, supplier)` (`utils.py:500-509`) applies
`supplier.sku_type`/`sku_value` as prefix/suffix, feeds
`copy_supplier_products_to_main_task`'s `MainProduct.sku`
(`supplier_product_manager/tasks.py:507`). The pre-copy PIM push this used to
agree with is gone. **The Excel upload no longer talks to PIM at all** — it
only has to produce the right `sku`, which becomes `product.Product.number`
via `link_unlinked_main_products` (the copy task's own link step), and
`number` plus the Product's brand is reindex's search key into PIM. `SupplierProduct.pim_id`
(`supplier_product_manager/models.py:17`) is dead weight — only the field
def and its migrations reference it, no read/write site (confirm with
[[supplier_product_manager]] if its code changes).

**It doesn't strip `article` — fine, because PIM does.** On the snapshot,
21% of Product numbers carry leading/trailing whitespace vs. 3 of PIM's
178,605; PIM strips whitespace on its side (confirmed by the user), so these
link normally in production. Don't "fix" it at import — the gap only shows
where matching happens *locally* against PIM's numbers
([[product]]'s `load_pim_mirror` loses ~400 matches to it).

## A ГП row always has a Product — by (sku, brand) since 2026-10-13

Since 2026-09-26 every write path creates the Product at once instead of
waiting for reindex. Since step 3 of «товар = бренд + артикул» the Product is
found by the pair: `resolve_product(sku, brand_id, name)` finds the
(`iexact` sku, brand) Product or creates it, and **without a brand it always
creates a new one**. `ensure_product(row)` wraps it for the admin
`save_model` and the import-export resource. Its brand defaults to the row's
price-list brand (`row_brand_id`). The modals call `resolve_product`
directly with the «Бренд» picker. The copy-to-main import calls
`link_unlinked_main_products(main_product_ids=touched)`, the same rule in bulk.
The whole mechanism and its traps are in [[product/identity]]. Traps worth
knowing here:

- `_link_to_local_product`/`link_to_local_products` (exact `number=sku`, never
  create) were **deleted**. A number alone no longer names a Product, and
  `get_pim_data_for_product` no longer links on the render path.
- Changing a row's sku or brand in the modal *moves* the row to that pair's
  Product (creating it). The nightly reindex never does this — it only links
  rows with `product IS NULL`.
- `resolve_product` strips whitespace; the import's `compute_supplier_sku`
  still doesn't (see above — PIM strips on its side).

## Open question — no path left to link different skus onto one Product

Dropping the Excel `ID` mapping removed the only way to put MainProducts
with **different** skus onto one Product — a new multi-supplier group now
only forms when two MainProducts share an identical `sku`. (The old main
page's `grouping.py`/`group_key()` that partitioned on this is gone entirely
with Phase 2b; whatever grouping `/products/` does now is [[product]]'s to
document.) Existing cross-sku links survive — migration `0007` touches only
`product.Product.pim_id`/`number`/`name`, never `MainProduct.product` — but
nothing creates new ones. **Not decided**; don't build a replacement
unilaterally.
