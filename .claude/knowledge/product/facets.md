---
title: Dynamic facet narrowing
summary: Filters that narrow to the current results and show counts, as a separate OOB request.
code: price_manager/product/filters.py, price_manager/product/views.py
---
# Dynamic facet narrowing

The brand/supplier/category checkbox lists on `/products/` hide options with
zero results under the current filters and show a live count next to each
option that remains — a second round-trip after every table refresh, kept off
the table's own response because it costs real time. Merged to `main` as
PR #234.

- **Two querysets, two purposes, don't conflate them.** `config_filters()`
  (`filters.py:282-291`, called from `__init__`) sets the **broad**
  querysets (all `Brand`, all `Supplier`) — purely so
  `ModelMultipleChoiceField` validates any pk that legitimately appears in
  the URL. It does **not** narrow to "used" brands/suppliers. `.qs` (table,
  export, cart) never calls `narrow_facets` and pays no facet cost. Narrowing
  happens only in `narrow_facets()` (`filters.py:318-372`), called by
  `ProductFilterView.get` (`views.py:190-196`, the first paint of the panel)
  and `ProductFacetsView.get` (`views.py:207-213`, route `product-facets` =
  `/products/facets/`, registered in `price_manager/urls.py:37`).
- **`_queryset_without(facet)`** (`filters.py:296-316`) computes "all
  conditions except this facet's own" — ticking Bosch under Brand must not
  hide Makita from the same list. Root is bare `Product.objects.all()`, not
  `self.queryset`: the page's annotations/ordering would pollute the
  aggregate. Wraps the result in `Product.objects.filter(pk__in=queryset
  .order_by().values('pk'))` — dropping `order_by()` is required because a
  search leaves `order_by(rank)` on the queryset, which would otherwise leak
  into the `GROUP BY` of the `Count`/`annotate` calls in `narrow_facets` and
  collapse every group to one product. Returns the base queryset unchanged
  (identity check `queryset is base`) when no other filter applies.
- **Writes land on `self.form.fields[...]`, never `self.filters[...].field`.**
  The form deep-copies its fields at construction, so writing to the filter
  field after that point never reaches the render (`filters.py:323-326`
  documents this explicitly). `narrow_facets` attaches `facet_counts` (dict
  `int pk → count`) to each form field, and `expanded_pks` to the category
  field. A selected option stays visible even at count 0 — taken from
  `cleaned_data`, i.e. already-validated instances, so junk in the URL can't
  reach the `pk__in` and can't fabricate a phantom option.
- **Counts must equal "select this option and count the results."**
  `test_every_count_matches_selecting_that_option`
  (`product/tests/test_filters.py:260`, class `ProductFacetNarrowingTests`
  at `:163`) drives every visible facet option through both a direct
  `.qs.count()` and the displayed count and asserts equality. Supplier count
  = distinct products with a `MainProduct` of that supplier
  (`filters.py:348-353`) — matches `supplier_method`'s own `Exists` exactly.
  Category count = **DISTINCT products in the node's whole subtree**, from
  raw SQL `category_subtree_counts()` (`filters.py:148-177`) joining the
  category-M2M-through rows to their ancestor categories on MPTT intervals
  (`tree_id`, `lft`/`rght`) — summing direct child counts would double-count
  a product that sits in two subcategories of one branch. Its output is
  ancestor-closed by construction (every counted node's ancestors are also
  counted), which is what makes it safe to feed straight to
  `{% recursetree %}`; a *selected* zero-count node still needs its
  ancestors added explicitly via `expanded_category_pks()`
  (`filters.py:132-145`) since a node with no products in its subtree isn't
  in the counts dict at all.
- **Measured cost on a prod snapshot (~159k products): 60–450 ms for
  `narrow_facets`, depending on how many conditions are active.** That is why
  facets are a **separate** request, not embedded in the table response.
  `ProductPage.render_to_response` (`views.py:82-93`) adds an `HX-Trigger:
  products-updated` header (`PRODUCTS_UPDATED_EVENT = 'products-updated'`,
  `views.py:32`) to every HTMX response — table refresh, search, pagination,
  sort, and column changes all trigger it, deliberately over-inclusive since
  a spare facets refresh is cheap to skip. `#product-facets-refresh`
  (`list.html:843`, hidden div, `hx-trigger="products-updated from:body"`,
  `hx-swap="none"`, `hx-sync="this:replace"`, `hx-include="#product-filter,
  #products-search"`) picks it up and fetches `/products/facets/`, which
  renders `build_facets_helper()` (`filters.py:495-513`) — **only** the two
  OOB fragments: the category tree root (`div_id_categories`,
  `hx-swap-oob="true"`) and the `#checkboxes` partialdef of the brand/supplier
  checkbox lists (`hx-swap-oob="outerHTML"`, `core/includes/checkbox_field.html:37-74`).
  The listener **must** sit outside `#product-filter` and
  `#products-filters`: inside the form it would inherit `hx-push-url`
  and the facets URL would land in the address bar, which
  `ProductExportView` reads from `window.location.search`.
- **`list.html` JS (from ~`:1113`)**: a facets response is dropped
  (`event.detail.shouldSwap = false`, `list.html:1135`) if the form's state
  changed since the request was sent — otherwise a slow facets response
  could untick a box the user ticked mid-flight. User-expanded accordion
  branches and each `.filter-scroll-list`'s `scrollTop` are captured before
  the OOB swap and reapplied after. Console `htmx:sendAbort` errors are
  **expected, not a bug** — `hx-sync="this:replace"` aborts a stale
  in-flight facets request when a newer one supersedes it.
- **Tree template perf trap (fixed).** `category_tree_node.html` used to do
  `node.get_descendants|values_list:'pk'|intersection:selected_values` twice
  per branch node — 2 queries per branch even with nothing selected in the
  facet. It now reads the precomputed `field.field.expanded_pks`
  (`category_tree_node.html:17,23`), computed once per request by
  `expanded_category_pks` and attached in `narrow_facets`/`config_filters`.
  Guarded by `test_facets_query_count_does_not_grow_with_the_tree` and
  `test_facets_query_count_with_a_selected_category`
  (`product/tests/test_views.py:413,423`) — same query count at 2 branches
  and 20. The cart's `MainProductFilter.config_filters` sets `expanded_pks`
  too (`main_product_manager/filters.py:195-196`) — without it no branch in
  the cart's tree renders expanded, since the template no longer computes it
  itself. `category_tree_field.html:29-31` now shows a "not found" message
  when the (narrowed) queryset is empty.
- Existing panel test `test_filter_panel_hides_empty_options_and_shows_counts`
  (`test_views.py:366`) covers brand/supplier hiding + counts; the older
  `test_filter_fragment_does_not_leak_template_comments`
  (`test_views.py:346`) had to be given categories with products — empty
  categories are now hidden from the panel, so the old fixture (categories
  with no products) stopped exercising the comment-leak bug it was written
  for.
- See [[core]] for the `facet_counts` rendering hook inside
  `checkbox_field.html` (shared across apps) and [[main_product_manager]]
  for the `expanded_pks` contract `MainProductFilter` must also satisfy.
