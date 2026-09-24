---
title: Supplier sku and linking to Product
summary: compute_supplier_sku and the open question of linking different skus to one Product.
code: price_manager/main_product_manager/utils.py
---
# Supplier sku and linking to Product

## `compute_supplier_sku` — the only thing left tying import to PIM

`compute_supplier_sku(article, supplier)` (`utils.py:500-509`) applies
`supplier.sku_type`/`sku_value` as prefix/suffix, feeds
`copy_supplier_products_to_main_task`'s `MainProduct.sku`
(`supplier_product_manager/tasks.py:244`). The pre-copy PIM push this used to
agree with is gone. **The Excel upload no longer talks to PIM at all** — it
only has to produce the right `sku`, which becomes `product.Product.number`
via `link_unlinked_main_products` (the copy task's own link step,
`supplier_product_manager/tasks.py:263`), and `number` is reindex's only
search key into PIM. `SupplierProduct.pim_id`
(`supplier_product_manager/models.py:17`) is dead weight — only the field
def and its migrations reference it, no read/write site (confirm with
[[supplier_product_manager]] if its code changes).

**It doesn't strip `article` — fine, because PIM does.** On the snapshot,
21% of Product numbers carry leading/trailing whitespace vs. 3 of PIM's
178,605; PIM strips whitespace on its side (confirmed by the user), so these
link normally in production. Don't "fix" it at import — the gap only shows
where matching happens *locally* against PIM's numbers
([[product]]'s `load_pim_mirror` loses ~400 matches to it).

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
