---
title: Supplier sku and linking to Product
summary: compute_supplier_sku, product_for_sku (every ГП row gets a Product at once) and the open question of linking different skus to one Product.
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
via [[main_product_manager/pim-link]]'s `link_to_local_products` (the copy
task's own link step, `supplier_product_manager/tasks.py:525-526`), and
`number` is reindex's only search key into PIM. `SupplierProduct.pim_id`
(`supplier_product_manager/models.py:17`) is dead weight — only the field
def and its migrations reference it, no read/write site (confirm with
[[supplier_product_manager]] if its code changes).

**It doesn't strip `article` — fine, because PIM does.** On the snapshot,
21% of Product numbers carry leading/trailing whitespace vs. 3 of PIM's
178,605; PIM strips whitespace on its side (confirmed by the user), so these
link normally in production. Don't "fix" it at import — the gap only shows
where matching happens *locally* against PIM's numbers
([[product]]'s `load_pim_mirror` loses ~400 matches to it).

## A ГП row always has a Product (2026-09-26)

The old rule — "import and the modal only *link* to an existing Product,
reindex *creates*" — is gone. `product_for_sku(sku, name)` (`utils.py`)
finds the Product with `number__iexact` or creates it; `ensure_product(row)`
wraps it for the create/edit modal, the admin `save_model` and the
import-export resource's `after_save_instance`. The copy-to-main import calls
`link_unlinked_main_products(main_product_ids=touched)` instead of
`link_to_local_products`, so it creates missing Products for exactly the rows
it touched. Traps worth knowing:

- `_link_to_local_product`/`link_to_local_products` still match **exactly**
  on `number=sku` and never create; they survive only on the render path
  (`get_pim_data_for_product`) and in their own tests. Don't use them for a
  write path — a case-variant sku neither links nor can be created there.
- Changing a row's sku in the modal *moves* the row to the Product of the new
  sku (creating it). The nightly reindex never does this — it only links
  rows with `product IS NULL`.
- `product_for_sku` strips whitespace; the import's `compute_supplier_sku`
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
