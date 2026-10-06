---
title: Hand-made ГП rows and the «Строка ГП» modal
summary: MainProductForm creates and fully edits a ГП row; what it locks (price-list rows, set rows, card-created sku) and how a sku change moves the row between Products.
code: price_manager/main_product_manager/forms.py, price_manager/main_product_manager/views.py
---
# Hand-made ГП rows and the «Строка ГП» modal

ГП rows are created and **fully edited — every price and the stock** — in one
modal, `MainProductForm` (`forms.py:10`), from the «Товары» toolbar or from the
product card. Default supplier: «Свой склад» ([[supplier_manager/own-stock]]),
sorted first. The form never creates a supplier-less row: those are set rows
only ([[product/set-rows]]).

What a missing `SupplierProduct` means for stock and pricing is in
[[main_product_manager/tasks]] and [[product_price_manager/pricing]]. A row is
«from the price list» exactly when it has one (`MainProduct.has_supplier_price_list`).

## What the form locks

- **Price-list row** — supplier and supplier article are `disabled`: the import
  finds the row by them, and the next upload would create the row again.
- **Set row** — supplier, sku, article, `prime_cost` and `stock`: they come from
  the components.
- **Created from the card** (`?product=<pk>`) — sku is the Product's `number`,
  disabled; the row is put on that Product directly.

Article may be empty only for «Свой склад» (its rows use the sku as article);
any other supplier needs its own article. The form is rendered with
`prefix='mp'` — the «Товары» filter has a `supplier` field too, and without the
prefix the ids collide when the modal opens over it.

## A row is always on a Product

`MainProductCreate` (`views.py:152`): from the card it sets `product` to the
card's Product; from «Товары» it calls `ensure_product` (Product by sku,
created if missing — [[main_product_manager/sku-and-linking]]). Success from
«Товары» redirects to the new row's card, since the list hides it in a
collapsed panel.

`MainProductUpdate`: **changing the sku moves the row** to the Product of the
new sku (`product_for_sku`, creating it) — the row's sku and the Product's
number are the same thing. The nightly reindex never moves a linked row; it
only links rows with `product IS NULL`.
