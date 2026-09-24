---
title: Views and the shopping tab
summary: core/views.py: shopping-tab and cart views and how they are wired.
code: price_manager/core/views.py
---
# Views and the shopping tab

## Views (`core/views.py`, ~711 lines)

The shopping-tab / cart feature is the whole file. `ShoppingTab*` — list, delete,
detail, export, export-download, import + preview + run (`:173`–`:471`).
`CartItem*` — detail, quick-add, add-set, confirm, unconfirm, remove,
product-select, add-products (`:472`–`:705`). Plus `PersistentNotification*`
(`:65`, `:81`), auth views (`:94`, `:114`), Bitrix24 login (`:123`, `:141`,
mechanism below), and `mainpage`. The user guide is not a page here any more
— it is release 0.0 in `releases` (data migration `0002`).

Templates in `core/templates/shopping_tab/` use the **`hx-swap-oob`** convention
throughout, not the modal-CRUD one — one action refreshes a status chip, a
summary panel and a list together without a reload. See the `htmx-oob-fragments`
skill. `_get_shopping_tab_items` (`:238`) and `_shopping_tab_summary` (`:247`)
are the helpers those fragments render from.

**The shopping-tab stock badge cannot distinguish "out of stock" from "never
synced".** `core/templates/shopping_tab/includes/stock_badge.html:2-8`
branches on `{% if product.stock %}`, and Django template truthiness makes
both `None` and `0` falsy, so a `MainProduct` whose stock has never been
synchronised renders identically to one genuinely out of stock — it shows
`product.supplier.msg_navailable` (default «Нет в наличии»,
`supplier_manager/models.py:85-86`).

This matters because [[main_product_manager]] treats `stock IS NULL` as a
distinct third state and defends it deliberately on the write path:
`update_stocks` filters on `Q(stock__isnull=True) | ~Q(stock=F('new_stock'))`
(`main_product_manager/utils.py:493`) precisely so never-synced products are
not permanently skipped, and the rule is pinned by
`UpdateStocksNullSafeTests` (`main_product_manager/tests.py:12`). The two
read-side renderers that used to conflate `None` and `0` the same way — the
old `main_product_manager/tables.py` `render_stock_msg` and
`Supplier.get_delivery_days_for_stock` — were **fixed under issue #155**:
the table moved to `product/tables.py:261-271`
(`SupplierRowTable.render_stock_msg`, now branches on `record.stock is None`
before touching the supplier) and `Supplier.get_delivery_days_for_stock`
(`supplier_manager/models.py:105-118`) now has an explicit `if stock is None`
branch with a docstring explaining why that is a third state, not a synonym
for "no stock". **This cart badge was out of that issue's scope and was not
touched** — it still conflates `None` and `0` via the plain-truthy
`{% if product.stock %}`. If the cart is ever revisited, it needs its own
fix; it doesn't inherit one for free from what #155 already shipped
elsewhere.
