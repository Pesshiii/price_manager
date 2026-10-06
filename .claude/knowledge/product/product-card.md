---
title: The product card — /products/<pk>/
summary: What the card shows and edits, why PIM fields are read-only on a mirrored Product, and why ГП rows are only ever moved and a Product is deletable only when empty.
code: price_manager/product/views.py, price_manager/product/forms.py, price_manager/product/templates/product/detail.html
---
# The product card — `/products/<pk>/`

`ProductDetailView` (`views.py:333`): the Product's ГП rows with their fixed
markups, set composition, and a lazily loaded PIM panel ([[product/pim-content]]).
Every action is a modal in `#modal-container`; success reloads the card (a
delete redirects to `/products/`).

- **Add a ГП row** — the «Строка ГП» modal with `?product=<pk>`, sku preset to
  the Product's number ([[main_product_manager/gp-rows-by-hand]]).
- **Fixed markup of a row** — the tag button opens `PriceTagCreate`/
  `PriceTagUpdate` ([[product_price_manager/pages-and-fixed-markups]]).
- **Edit / delete the Product**, **attach / move ГП rows** — below.

## Edit — PIM fields are read-only on a mirrored Product

`ProductForm` (`forms.py:44`) edits `number`, `name`, `brand`, `categories`.
When the Product has PIM content (`raw_data` non-empty) `name`, `brand` and
`categories` are **disabled**: `apply_pim_product` overwrites them on every
sync ([[product/pim-sync]]), so they are fixed in PIM. A Product without PIM
data (most of them) is fully editable. `number` is always local — PIM never
sends it — and is the key new ГП rows link by.

## ГП rows are moved, never unlinked

`MainProductAttachView` («Привязать строку ГП», pull a row from another Product)
and `MainProductMoveView` («Перенести в другой товар») both just set
`MainProduct.product` (`_relinked`, `views.py:448`). There is deliberately no
"unlink": `link_unlinked_main_products` re-links an unlinked row **nightly** to
the Product numbered by its sku, **recreating** that Product if missing — while
it never touches an existing link, so a hand-made move sticks.

## Delete — only a Product with no ГП rows

`ProductDeleteView` refuses while `main_products.exists()` («перенесите их в
другие товары»). For the same reason: a Product deleted with rows on it would
come back by itself the next night. Move the rows first, then delete.
