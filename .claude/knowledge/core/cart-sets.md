---
title: Sets in the cart
summary: add_set_to_cart, CartItem.source_set, CartItemAddSetView and the «Набор» export column.
code: price_manager/core/utils.py, price_manager/core/views.py
---
# Sets in the cart

## Sets in the cart — `add_set_to_cart` (PR #233, 2026-09-24)

`add_set_to_cart(tab, set_product, quantity, user)` in `core/utils.py:213`
(`@transaction.atomic`, `:212`) explodes a `product.Product` set into one
ordinary `CartItem` per `ProductSetItem` line — quantity = line amount ×
number of sets requested. Candidates (`item.products`) are the component's
own `MainProduct` rows (`MainProduct.objects.filter(product=component)`), not
a text search — the component is already known exactly. `confirmed_product`
is set straight to `line.cost_row` when `line.has_cost` — the same supplier
row the «Из комплектующих» total on `/products/` picked via
`product.set_costs.set_totals_for` (see [[product]]) — so add-set both
creates and confirms the line in one step; a component with no priced
supplier row is left unconfirmed. A component **missing from Price Manager
entirely** (no `MainProduct` match) still becomes a line — `search_query`
falls back to the PIM component name/number off `line.item` — so nothing to
buy silently disappears from the exploded set. It never merges with
already-present cart items (consistent with the rest of the cart, which
never merges); each new line is tagged `source_set=set_product` and shown as
«из набора X» (`core/utils.py:205` `set_label`).

`set_label()` also drives the **last** column, «Набор», of the shopping-tab
xlsx export (`SHOPPING_TAB_EXPORT_COLUMNS`, `core/utils.py:134`) — appended at
the end deliberately, per the comment at `:144-146`, so existing column order
doesn't shift for whoever consumes the export downstream. `set_totals_for`
returning `None` for the set (e.g. it has no set items after all) makes
`add_set_to_cart` a no-op returning `[]`.

**`CartItemAddSetView`** (`core/views.py:542`), route
`cart-items/add-set/<int:product_pk>/` name `cart-item-add-set`
(`price_manager/urls.py:107`). Keyed on `product.Product`, not `MainProduct`
like `CartItemQuickAddView` — a set may have no supplier rows of its own.
`get_set` 404s via `Product.objects.filter(set_items__isnull=False).distinct()`
if the product isn't actually a set. `get_tabs` filters
`ShoppingTab.objects.filter(user=self.request.user)` — posting a foreign
tab's pk just fails the `tabs.filter(pk=selected_tab).first()` lookup, no
leak. GET/POST both bail to `redirect('products')` for a non-htmx request.
Templates `shopping_tab/partials/set_add_modal.html` /
`set_add_result.html` — bootstrap-classes-only like `quick_add_*`, because
`/products/` doesn't load `shopping_tab`'s own styles. `views.py` reaches
`add_set_to_cart` through its existing `from .utils import *`.

Two ways a set reaches a cart: an **assembled** set (has its own `MainProduct`
rows) goes through the ordinary quick-add button on its supplier row; *any*
set (assembled or not) can go through the new cart-plus button inside the
«Из комплектующих» `<summary>` row
(`product/templates/product/partials/set_assembly.html:15-25`) — a `<button>`
nested inside a `<summary>` does not toggle the parent `<details>` on click
(verified: the button's own click handler runs, `<details>` stays as it was).

There is still no «delete a line from a tab» primitive anywhere in `core`
(only `CartItemRemoveProductView`, which removes a *candidate* from a line's
`products`, not the line itself) — «remove a whole exploded set in one go»
was deliberately deferred for that reason; deleting the source set itself
does nothing to the cart items either (`source_set` is `SET_NULL`).

Tests: `core/tests.py` `AddSetToCartTests` (line 782, 10 cases) — reuses
`product.tests.test_set_costs.SetFixture` rather than building its own set
fixture.
