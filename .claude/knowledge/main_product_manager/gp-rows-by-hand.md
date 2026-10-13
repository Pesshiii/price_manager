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

`MainProductCreate`: from the card it sets `product` to the card's Product
(sku and brand pickers disabled). From «Товары» it calls `resolve_product(sku,
brand)` with the modal's «Бренд» picker: the (sku, brand) Product is found or
created, and **a row without a brand always gets a new Product**
([[product/identity]]). A brandless row that lands next to other Products with
its number gets an info toast suggesting a move. Success from «Товары»
redirects to the new row's card, since the list hides it in a collapsed panel.

`MainProductUpdate`: **changing the sku or the brand moves the row** to that
pair's Product (`resolve_product`, creating it). A price-list row's brand is
its supplier's (`row_brand_id`), and its picker is disabled. The nightly
reindex never moves a linked row; it only links rows with `product IS NULL`.

`brand` is a declared, non-model form field. The picker partial needs
`name=form.brand.html_name` (`mp-brand`) because of the form prefix.
