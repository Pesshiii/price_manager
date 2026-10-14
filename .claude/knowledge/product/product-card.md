---
title: The product card — /products/<pk>/
summary: What the card shows and edits, why PIM fields are read-only on a mirrored Product, and why ГП rows are only ever moved and a Product is deletable only when empty.
code: price_manager/product/views.py, price_manager/product/forms.py, price_manager/product/templates/product/detail.html
---
# The product card — `/products/<pk>/`

`ProductDetailView` (`views.py:335`): the Product's ГП rows with their fixed
markups, set composition, and a lazily loaded PIM panel ([[product/pim-content]]).
The header carries a photo carousel with an enlarge modal ([[product/photos]]).
Every action is a modal in `#modal-container`; success reloads the card (a
delete redirects to `/products/`). The photo modal is a separate
`#pd-photos-modal`, because HTMX forms swap `#modal-container`'s content.

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
sends it — and with `brand` is the pair new ГП rows link by. `ProductForm.clean`
refuses a (number, brand) pair another Product holds, with a link to it;
brandless Products may share a number ([[product/identity]]).

## ГП rows are moved, never left unlinked

`MainProductAttachView` («Привязать строку ГП», pull a row from another Product)
and `MainProductMoveView` («Перенести в другой товар») both just set
`MainProduct.product` (`_relinked`). There is deliberately no plain "unlink"
(product = NULL): `link_unlinked_main_products` re-links an unlinked row
**nightly** to the Product of its (sku, brand) pair — a new Product if it has no
brand — **recreating** that Product if missing, while it never touches an
existing link, so a hand-made move sticks.

«Отвязать в новый товар» (`MainProductDetachView`, a button in the move modal) is
a move into a Product made for the row: `resolve_product(sku, row_brand_id)` when
that pair is not the current Product's, otherwise a new **brandless** Product
(the same pair would just return the old one). A no-claim price-list row carries
the old Product's brand as inherited, so its pair is always the same and it
always gets a brandless Product. Set rows are refused (`set_rows` keys them by
product). The old Product may be left with no rows; delete it by hand.

## Delete — only a Product with no ГП rows

`ProductDeleteView` refuses while `main_products.exists()` («перенесите их в
другие товары»). For the same reason: a Product deleted with rows on it would
come back by itself the next night. Move the rows first, then delete.
