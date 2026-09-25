---
title: The /products/ page — rendering traps
summary: Traps found only by driving /products/ in a browser — shared partials, scripts, CSS scoping, sort limits.
code: price_manager/product/templates/product, price_manager/product/tables.py
---
# The /products/ page — rendering traps

Split out of [[product/products-page]]: these were all found by driving the
page in a browser, not by measurement, and a green suite missed every one of
them.

- **The filter partials are shared: an edit lands on every screen that
  renders them.** `category_tree_field.html`/`category_tree_node.html`:
  `product/filters.py:478,508` and `main_product_manager/filters.py:122`
  ([[main_product_manager]]'s cart picker).
  `core/includes/checkbox_field.html`: `product/filters.py:480,482,509-510`
  (render its `#checkboxes` partialdef on the OOB path — see [[core]]),
  `main_product_manager/filters.py:126,130` and
  `supplier_product_manager/filters.py:108`. `radio_field.html` emits the
  same classes via `CustomRadio('supplier')` in the «Добавить
  товар» form (`main_product_manager/forms.py:43`). The tree needs an
  ancestor-closed queryset — `recursetree` on an orphaned node raises, a 500
  in the cart modal — so `MainProductFilter` adds
  `get_ancestors(include_self=True)` (`main_product_manager/filters.py:191`);
  `ProductFilter.narrow_facets` does the equivalent by unioning
  `category_subtree_counts` (ancestor-closed by construction) with
  `expanded_category_pks` of the selection (`filters.py:365-372`) — **not**
  "the whole tree". The tree's root id `div_<auto_id>` is the OOB-swap target
  for `ProductFacetsView`'s refresh on `/products/`
  (`category_tree_field.html:20`) — since «Привязать из ГП» and its stripped
  render left `MainProductFilter` (#231), the only one. Rename it and the
  refresh silently stops.
- **Checkbox/radio-facet `<script>` blocks must not declare at top level —
  they run once per facet.** `core/includes/checkbox_field.html` and
  `radio_field.html` are included once per facet (brand, supplier), so a
  bare `const`/`let` at the top of the inline `<script>` throws `SyntaxError:
  Identifier has already been declared` on the second include (PR #191, fixed
  by gating everything behind `window.__priceManagerCheckboxFilterInit` /
  `__priceManagerRadioFilterInit`). Guarded by
  `test_filter_panel_scripts_declare_nothing_at_top_level`
  (`product/tests/test_views.py:220-237`), which greps the rendered scripts
  for a top-level `const`/`let`/`class`.
- **`/products/`'s CSS is scoped by page-specific class names**
  (`list.html`, `{% block style %}` starting `:8`). Every selector is
  anchored on a `.products-*`/`#products-*` class this page emits; what
  touches shared filter markup sits behind `.products-sidebar`. No bare
  `.form-check`/`.accordion`: `base.html` reaches every page.
  `.filter-scroll-list`/`.filter-check-item`/`.filter-actions` are styled
  **only** at `list.html:137,147,217` — the old main page carried the rules
  and Phase 2b-1 deleted it, leaving the shared markup with none. The tree
  keeps its own inline `max-height` (`category_tree_field.html:24`); the
  «Добавить товар» modal (`#modal-container`, `list.html:942`) sits outside
  `.products-sidebar` and needs none of this. Unbounded facet list? Check the
  page still carries these rules before debugging the markup.
- **A multi-line `{# … #}` is not a comment in Django — it renders as text.**
  The lexer matches `{#.*?#}` without `DOTALL`, so a `{#` whose `#}` is on a
  later line is literal, and any tag inside it executes. Both
  `category_tree_node.html` (leaf branch, now `{% comment %}` at `:33-41`)
  and `product/partials/table.html` (top-of-file note, now `{% comment %}`)
  had this. Guarded by `test_filter_fragment_does_not_leak_template_comments`
  (`test_views.py:346`) and
  `test_fragment_does_not_leak_template_comments_into_the_response`
  (`test_views.py:158-167`).
- **The name column cannot sort — by construction — and there is no sort by
  brand.** `ProductTable.display_name` is `orderable=False` (`tables.py:200`):
  `Product.display_name` is a `@property`, not a column, so the database
  can't order by it (a sortable name would need an annotation reproducing the
  fallback — `Coalesce`, untried). Sort links come from `column.orderable`
  (`partials/table.html:33`): only `number`, `supplier_count`, `total_stock`
  sort. Brand and categories render as a `brand · category · …` line under
  the name (`tables.py:286-288`), not columns — hence no brand sort.
  `_base_queryset` (`views.py:35-50`) keeps `select_related('brand')` and the
  categories prefetch for that cell; drop either and it's N+1, unguarded by
  `assertNumQueries`.
- **Known gap, not fixed — the mobile filter drawer stays open after a
  checkbox tick.** Below `lg` the filters sit in an offcanvas
  (`#products-filters`, `list.html:811`) closed only by a `submit` listener
  on `#product-filter` (`list.html:1175-1180`), i.e. by «Применить». A tick
  auto-applies via `hx-trigger` `change delay:600ms` (`filters.py:456`),
  which fires no `submit`, so the drawer stays open over the refreshed
  results.
