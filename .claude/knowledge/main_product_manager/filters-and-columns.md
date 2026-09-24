---
title: Brand data, MainProductFilter, derived columns
summary: Where brand lives after Phase 2b, the cart's MainProductFilter, three columns that are not fields.
code: price_manager/main_product_manager/filters.py
---
# Brand data, MainProductFilter, derived columns

## Where brand data lives after Phase 2b

`MainProduct.manufacturer`/`SupplierProduct.manufacturer` are gone (confirmed
absent from both models). Brand is `product.Product.brand` (PIM only). If
reading an old analysis: `MainProduct.manufacturer` used to hold *whichever
ran last* of copy-to-main (supplier value) or `sync_pim_relations` (PIM
brand) — never raw supplier data.

## `MainProductFilter` is the cart's filter, not a page's (`filters.py`)

Since Phase 2a it serves the cart's «Добавить товары» modal
(`core/views.py` `CartItemProductSelectView`), shopping-tab import
auto-match (`core/utils.py` `find_main_products`). «Привязать из ГП»
(`ResolveMainproduct`, `/resolve`) was removed from the card on 2026-09-24.
Rows are MainProduct, but search/brand/categories go
**through `MainProduct.product`** via [[product]]'s shared
`matching_product_pks`. Must not touch `MainProduct.search_vector`/
`.categories`/`.manufacturer` (removed from the model, confirmed absent from
`filters.py`); `core/views.py` imports it at module scope
(`core/views.py:33`) — a stale field reference stops the whole app booting.
Rows without a Product are still found by own `sku`/`name`/`article` (in the
cart, invisible would mean unbuyable).

**Category tree expansion is computed by the filter, not the shared
template.** `product/templates/product/partials/category_tree_node.html:17,23`
just reads `node.pk in field.field.expanded_pks` — see [[product]] for the
full mechanism. `MainProductFilter.config_filters`
(`filters.py:208-209`) sets it via `product.filters.expanded_category_pks`
(one query: selected category pks + their ancestors). It must be set on
`self.filters['categories'].field` inside `__init__`, before the bound form
is built (`config_filters` runs at `filters.py:88`) — a Filter's `.field` is
built once and shared with the form, so setting the attribute later would
miss the render. Silent failure mode: without `expanded_pks`,
`node.pk in None` is falsy under Django's `{% if %}`, so the tree just
renders every branch collapsed, including one holding a ticked category —
no error anywhere. Any new filter that reuses this tree partial must set
`expanded_pks` the same way.

The old main page — `MainPageFilter`, `MainProductTable`, `grouping.py`,
`columns.py`, the column-preference cache — was deleted in Phase 2b
(confirmed gone repo-wide); `/mainproduct/` permanently redirects to
`/products/` (`urls.py:13`, no query params carried over). This app's own
`urls.py` still owns the per-row routes: create/update/info/detail/
logs and the pricetag-list proxy (`urls.py:15-23`). This app's `tables.py` is
tiny now too — `MainProductLogTable` only. The card's «Наценки» column
(`product_price_manager` `PriceTagList`) splits PriceTags into «Фиксированные»
(`p_manager IS NULL`, editable in place) and «Из менеджеров наценок» (opens the
rule's modal — a rule's apply overwrites its tags, so they are not edited here).

## Three columns that look like fields but aren't

`MainProductLog` has three writers: `utils.update_logs()` (`utils.py:819-853`
— has leftover `print()` debug calls in its body) and
[[product_price_manager]]'s `PriceManager.apply(logs=True)` /
`PriceTag.get_mp()` (the latter reached unconditionally every run via
`update_prices()`).
`supplier_product_price`/`supplier_product_rrp`/`supplier_product_discount_price`
are not `MainProduct` fields but correlated Subqueries over the latest
`SupplierProduct` row, now built in [[product]]'s
`views._latest_supplier_prices()`.
