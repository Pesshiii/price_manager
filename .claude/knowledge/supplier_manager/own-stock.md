---
title: «Свой склад» — the own-stock supplier
summary: Supplier.is_own_stock: one real supplier for leftover stock, returns and bonuses; how it is found, protected, and what the flag does and does not mean.
code: price_manager/supplier_manager/models.py, price_manager/supplier_manager/views.py, price_manager/supplier_manager/forms.py, price_manager/product_price_manager/migrations/0009_unsupplied_supplier.py, price_manager/product_price_manager/migrations/0010_own_stock.py
---
# «Свой склад» — the own-stock supplier

«Свой склад» (until migration 0010, «Без поставщика») is a **real `Supplier`**
with `is_own_stock=True`. It holds leftover stock, returns and bonuses, and has
everything any supplier has: upload, copy to ГП, its own `PriceManager`s,
levels, delivery days. See [[main_product_manager/gp-rows-by-hand]]
for the rows typed into it by hand.

## For stock and pricing it is an ordinary supplier

Neither `update_stocks` nor the pricing rules branch on the flag. A hand-made ГП
row of this supplier is not special because of it: **any** supplier's row
without a `SupplierProduct` is hand-made and handled by the general rules
([[main_product_manager/tasks]], [[product_price_manager/pricing]]).

Where the flag does matter:

- it is the **default supplier** of the «Строка ГП» modal
  (`main_product_manager/forms.py`, `Supplier.own_stock().pk` as initial), sorted
  first there and in the rule form (`order_by('-is_own_stock', 'name')`), and
  the only supplier whose rows may omit the supplier article — the sku serves as
  it ([[main_product_manager/gp-rows-by-hand]]);
- it is **where retired and stray set rows go**: `_retire_stale_rows` moves a
  former set's row and any supplier-less non-set row here ([[product/set-rows]]);
- the protections below. (In the product export it is simply one more
  supplier sheet; the «Наборы» sheet is the supplier-less set rows.)

## Finding it — `Supplier.own_stock()` (`models.py:143`)

Looked up **by the flag only**. A supplier merely *named* «Свой склад» is never
taken over: on a clean database `own_stock()` creates the flagged one and, if
the name is taken, gives it a numbered name («Свой склад 2»). A partial
`UniqueConstraint` on `is_own_stock` (`condition=Q(is_own_stock=True)`,
`models.py:134`) allows only one.

## Protections

- **Pinned first** on `/supplier/` (`views.py:130`, sort on `is_own_stock`).
- **Not deletable**: `SupplierDelete.get_queryset` excludes it (`views.py:189`),
  so a delete is a 404 — hand-made rows and retired set rows hang off it.
- **Not renamable**: `SupplierForm` disables `name` for it (`forms.py:80`) — the
  name is how people recognise it in every list.

## Migration history — 0009 and 0010

- `product_price_manager/0009_unsupplied_supplier` created it (or flagged an
  existing supplier of that name — unlike `own_stock()` today), moved the
  supplier-less non-set rows to it, cloned every supplier-less rule onto it
  (suffix « (без поставщика)») with those rows' tags, and gave each moved row a
  **synthetic `SupplierProduct`** carrying its stock — then the only way to stop
  `update_stocks` zeroing it and to let a supplier rule reach the row.
- `supplier_manager/0016` + `product_price_manager/0010_own_stock` renamed it
  (only if the old name was not taken by another supplier, and the rule copies'
  suffix « (без поставщика)» → « (свой склад)» when free), and **deleted the
  synthetic `SupplierProduct`s** — but **only when «Свой склад» has no upload
  `Setting`**. With a setting, a synthetic row looks exactly like a row that
  fell out of the file, and deleting it would make the next copy-to-ГП create a
  second ГП row; such a database is left for manual cleanup. Not reversible.
  The deletion goes through historical models, so the `post_delete` signal that
  zeroes stock does not fire — deliberately (see [[main_product_manager/tasks]]).
