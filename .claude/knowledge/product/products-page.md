---
title: The /products/ page — traps
summary: Page traps found on real data — search ranking, category facet, ordering, HTMX wiring.
code: price_manager/product/views.py, price_manager/product/tables.py, price_manager/product/filters.py
---
# The /products/ page — traps

`ProductFilter` (`filters.py`), `ProductTable` (`tables.py`), `ProductPage`
(`views.py`), `product/list.html` + `partials/`. Every trap below passed a
green suite and was caught only by measuring on the prod snapshot or driving
the page in a browser. Rendering-only traps (found by driving the page in a
browser, not by measurement) live in [[product/products-page-rendering]].

- **`SearchRank(F('search_vector'), …)`, never `SearchRank('search_vector', …)`**
  (`filters.py:43-58`). With a string, Django re-tokenizes the stored tsvector
  as text on every row with the default config, bypassing the GIN index.
- **Rank order needs `nulls_last=True`** (`filters.py:101-115`, `ranked()`).
  `'-rank'` compiles to `ORDER BY rank DESC`, and Postgres puts NULLs *first*
  on DESC. Products with no PIM data have no vector, so their rank is NULL,
  and they filled all of page 1 on every search measured.
  `test_full_text_match_ranks_above_a_supplier_name_only_match` guards this.
- **Search is a UNION, not an OR** (`matching_product_pks`, `filters.py:61-98`).
  Vector, `number__icontains` and the MainProduct-name `Exists` are each
  cheap alone; OR'd together Postgres can't combine the GIN scan with the
  subquery and scans everything (622ms vs 263–586ms measured).
- **The category facet needs `select_related` to depth 5**
  (`CATEGORY_LABEL_DEPTH`, `filters.py:184`, used at `filters.py:224`).
  `Category.__str__` recurses through `self.parent`: 1,567 queries / 1.6s on
  the real tree vs 1 query / 36ms.
- **The category facet is a tree, not a checkbox list**
  (`product/partials/category_tree_field.html` + `category_tree_node.html`,
  `{% recursetree %}`, shared — see [[product/facets]]). A flat list was 668
  rows with paths up to 126 chars.
- **`ProductPage.get_template_names()` must return the table fragment for
  HTMX** (`views.py:95-111`). Filter and search both `hx-get` back to
  `products`, not a separate fragment endpoint — so `hx-push-url` keeps the
  address bar correct. Without the `request.htmx` branch the whole page
  renders inside `#products-table`.
- **The search widget needs an explicit `id='products-search'`**
  (`filters.py:216`). Django's default `id_search` isn't what
  `hx-trigger`/`hx-include` select on.
- **`self.data` is not always a QueryDict** — `selected_values()`
  (`filters.py:27-40`) handles a plain dict, since django-filter 25.1 only
  swaps a *falsy* `data` for an empty `QueryDict`. [[supplier_product_manager]]'s
  `SupplierProductFilter` calls `self.data.getlist()` bare and raises
  `AttributeError` from `__init__` if built from a plain dict.
- **Search is shared, not copied.** `filters.py` exposes
  `matching_product_pks`, `ranked`, `search_rank`, `category_with_descendants`,
  `selected_values`, `expanded_category_pks`, `category_subtree_counts` at
  module level; [[main_product_manager]]'s `MainProductFilter` (cart's
  product picker) imports and reuses several of them
  (`main_product_manager/filters.py:8-11`, includes `expanded_category_pks`).
  Change search or the tree-expansion rule here and the cart changes with
  it — that is the point.
- **`price_from`/`price_to` filter on `MainProduct.prime_cost`**
  (`filters.py:264-274,428-436`) via the same `_with_main_product(Exists(...))`
  helper as `supplier`/`available` (`filters.py:400-403`) — added with the
  PR #197 redesign, no surprise mechanism, just note it exists if you're
  looking for "cost" and don't see a field on `Product`.
- **Column preferences (`columns.py`) are cached per user under
  `product_page:columns:user:<id>`** (`columns.py:95`) — a separate key from
  the supplier-detail page's `supplierdetail:selected_columns:user:<id>`
  ([[supplier_product_manager]]). `normalize_columns` keeps catalog order and
  turns an empty choice into `DEFAULT_COLUMNS`, never zero columns. The
  picker's hidden empty `columns=` (`columns_picker.html:32`) is there so
  that «снял всё» still sends the key: with no `columns` in the request the
  view loads the saved choice instead of saving (`views.py:149-153`).

### Default order is by category — `annotate_product_rows(by_category=True)`

With no `sort`, rows are ordered by category tree position and `table.html` puts a
breadcrumb header row over each group (and over row 1 of every page).
`ProductPage.groups_by_category()` is the one switch, and only a column sort turns it
off. The view decides it, not the template, because `table.html` is also the HTMX
fragment.

**Search keeps the groups** (the owner's call, 2026-09-22):
`ProductPage.get_table_data` reorders the ranked queryset with
`best_match_groups_first` — groups by `MAX(rank) OVER (PARTITION BY category_key)`,
then `category_key`, then `rank`, all `nulls_last`. Plain relevance order would put a
header over nearly every row, and plain tree order would push the best match onto a
later page. The trade-off is accepted: a group's weak matches come before a stronger
match from the next group. `search_method` still ranks through `filters.ranked`
unchanged — the cart's `MainProductFilter` shares it. The regrouping happens only on
this page, after the filterset. About 110–130 ms per page on the snapshot.

The key is chosen by measurement on the snapshot:

- **Not a correlated subquery.** `ORDER BY (SELECT … FROM categories WHERE product_id = p.id …)`
  runs on all 158k rows: 8 s with the m2m seq-scanned, ~1.1 s when forced onto the index.
  The key is instead `Min(ARRAY[tree_id, lft])` over a join on `categories`: 0.6–0.7 s,
  against 0.42 s for the old `-updated_at` default, with ~54k m2m rows seeded in a
  rolled-back transaction (the snapshot itself has only 383).
- **An array, not `Min(tree_id)` + `Min(lft)`.** For a product with two categories those
  come from different categories, so the key names neither one. `primary_category()`
  in `tables.py` must apply the same rule in Python (first category in tree order), or a
  row sorts under one group and shows another group's header.
- **That join doubles `Sum`.** `Count(distinct)` and `Min`/`Max` survive it, but
  `total_stock` would count stock once per category. So in this mode `total_stock` is a
  `Subquery`. Postgres evaluates a target-list subplan after the `LIMIT` (`loops=25`),
  so it costs nothing. **Don't make it a Subquery always:** «Остаток» is sortable, and
  sorted by it the subquery runs for every row (2.6 s against 0.48 s).
  `test_product_with_two_categories_is_listed_once_and_its_stock_is_not_doubled`
  guards this. The snapshot cannot, because it has zero multi-category products.
- ~64% of `Product`s have no PIM category (see [[product/pim-sync]] for coverage
  numbers). All of them are one «Без категории» group at the tail, ordered by stored
  `name`, which unsynced rows may lack.
- Header paths come from the categories prefetch, now
  `Prefetch(..., Category.objects.select_related(CATEGORY_LABEL_DEPTH))` in
  `_base_queryset` (`views.py:35-50`). Walking `parent` without it is a query per level.
- **The paginator's `count()` keeps the `total_stock` subquery** in its inner select,
  because it is a non-aggregate annotation. Postgres drops the unused output, so the
  count stays at ~70–120 ms. Time the SQL Django actually emits
  (`CaptureQueriesContext`), not a hand-written count — a hand-written one is how
  this went unchecked.

### Search and filters have to include each other

The filter form carries `hx-include="#products-search"` (`filters.py` `build_helper`),
and the search form carries `hx-include="#product-filter"` (`list.html`). The second
half was missing until 2026-09-22: typing a search sent only `search=`, so the panel
still showed ticked filters while the results and the pushed URL ignored them.
`test_search_form_sends_the_filters_along` guards it. Any new control that `hx-get`s
`products` needs both selectors, as `columns_picker.html` already does. Neither form
carries `sort`, so a search or a filter change drops a column sort and grouping comes
back — an existing behaviour, left alone.
