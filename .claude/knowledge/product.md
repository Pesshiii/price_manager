# product

**Read this before assuming anything about `product`.** PR #184 changed what
`Product.pim_id` *means*; the product-shift Phase 1 (2026-09-19) made
`Product` the root of search and filtering at `/products/`; PR #197
(2026-09-2x) redesigned that page (sticky filters, compact table, search
fixes). Re-verify anything below that predates those if this file looks old.
Design and decisions: `.claude/shift-to-product-brief.md`.

## What it is *now*

A **PIM-linked mirror**, being deliberately recreated and reconnected to the
live legacy stack — treat anything here as in-motion; check
`git log -- product/` if something surprises you.

`product/models.py` — read the whole thing:
- `Category(MPTTModel)` — `parent`(PROTECT) / `name` / `slug` / `pim_id`,
  unique constraint on `(parent, name)`, `order_insertion_by = ['name']`.
  `save()` auto-generates a unique `slug` via `slugify(allow_unicode=True)`
  with a `-2`, `-3` … suffix loop. **`__str__` recurses through `self.parent`**
  — see the N+1 trap below.
- `Brand` — `pim_id` (unique, PIM `brandId`), `name`. **Keyed on the id, never
  the name**: a PIM rename would otherwise fork one brand into two (real: R5,
  2026-09-21, 14 groups like STAYER/Stayer across 321 brands, merged in PIM
  not here). No alias layer by design — `supplier_manager.ManufacturerDict`
  solved that for supplier names, had 0 rows in prod, retired in Phase 2b-3.
  Added later than the rest of the model, in migration `0008`, alongside
  `search_vector`.
- `Product` — `pim_id` (nullable, unique — see next section for what it now
  identifies), `number` (unique, nullable, the local match key =
  `MainProduct.sku`, never overwritten from PIM), `name` (**not** unique),
  M2M `categories`, FK `brand` (nullable — PIM returns `brandId` as a
  **scalar**, hence FK not M2M), `raw_data` JSON, `search_vector` + GIN
  (`product_search_vector_gin`, `config='russian'`), timestamps.
  `ordering = ['-updated_at']`.
- `Product.display_name` (`models.py:113-126`) — `name`, else the first linked
  MainProduct's name, else (none linked) `number`, else `pim_id`. Needed because
  `name` comes from PIM and most Products (still true as of the last measured
  pass — see coverage below) have no PIM content at all.
- `Product._build_searchvector()` (`models.py:128-151`) builds **only from
  `raw_data`** — no network call. Joins with `' '`, not `''`: the old
  `MainProduct` version glued category names into one token, so neither word
  was searchable.

## `Product.pim_id` now names a PIM `PriceManagerProduct` (PMP), not a PIM `Product`

Before this branch, `pim_id` was the id of a PIM `Product`. Now it's the id of
a PIM **`PriceManagerProduct`** — a through record whose `platformID` is our
`Product.pk` and whose `productId` points at the PIM `Product`. The full link
chain, who pushes it (`reindex_pim_ids`), and the two-hop read path are owned
by [[main_product_manager]] — don't restate them here. Product-owned
consequences:

- `pim_id` stays `NULL` on a `Product` until that reindex pushes its PMP. A
  fresh `Product` with no `pim_id` is normal, not broken
  (`test_products_without_pim_id_coexist`).
- Most `Product` rows today are created **locally**, not by PIM sync or by a
  seed migration: `main_product_manager.utils.link_unlinked_main_products`
  creates `Product(number=sku, name=<that MainProduct's name>)` with `pim_id`
  left `NULL`. Don't assume a `Product` with data came from
  `sync_product_from_pim` or `0005`'s seed.
- `name` **stopped being unique** (it was, briefly, under `0006`): several
  local `Product`s can point at one PIM `Product` (PIM `Product` hasMany
  `priceManagerProducts`), and PIM's own metadata doesn't declare
  `Product.name`/`Product.number` unique either
  (`test_name_is_not_unique`, `product/tests/test_models.py`).

## Migration `0007_product_pim_id_is_price_manager_product` — the meaning-change migration

The worked example for tightening/loosening a constraint on `Product` against
a populated database (`0006` used to be it — same step-ordering shape, plus a
cross-app dependency wrinkle here):

1. `AlterField pim_id → nullable` (`:55`) first — the next step can't write
   NULLs into a NOT-NULL column.
2. `RunPython(reset_pim_ids)` (`:27`) nulls **every** `pim_id` unconditionally
   — the old values are PIM `Product` ids, meaningless under the new schema.
   `reindex_pim_ids` re-derives them by `number` search.
3. Same RunPython deletes "residue": `Product`s with `number IS NULL` that
   nothing references — checked against `MainProduct.product`,
   `supplier_feed.SupplierFeedEntry.product` **and**
   `supplier_feed.SupplierLink.product` (`:36-41`). `SupplierLink.product` is
   `on_delete=CASCADE`; skipping that exclusion would silently take a
   supplier link down with its "orphan" `Product`.
4. Then `AlterField` on `number` (verbose name only) and `name` (drops
   `unique=True`).

Depends on `main_product_manager.0011` and `supplier_feed.0001` (`:48-51`)
because the `RunPython` reads those apps' models — a real cross-app migration
dependency, not just ordering. Not reversible on data (reverse is noop).
**CI migrates an empty database**, so this data step never meets a row there —
`product/tests/test_migration_0007.py` (imports the module via `importlib`
since its name starts with a digit, calls `reset_pim_ids` directly against
real rows) is the only coverage. **Deploy note:** run
`manage.py run_task reindex_pim_ids` right after migrating — no PIM data shows
on any `Product` until it re-pushes.

`0005_seed_products_from_main_product_pim_ids` bulk-creates a bare
`Product(pim_id=pim_id, number=None)` per then-existing `MainProduct.pim_id`
and never touches `name` — every seeded row lands with `name=''` (Django's
default for a nullable `CharField`) — invisible to CI since `0005` seeds zero
rows there. `0006_alter_product_name` added a unique constraint on `name`
despite that (nullable → `RunPython` turning `''` into `NULL`, raising with
the offending duplicate values rather than a bare `IntegrityError` →
`AlterField unique=True`); `0007` removes the constraint again for the reason
above, repeating the same three-step shape. `0002`/`0003` briefly carried
embedding/characteristics-era fields (`sku`, `characteristics`,
`embedding_text_hash`, an FK to `supplier_manager.Manufacturer`, a
`product_chars_gin_idx`); `0003` removes every one of them — see "What it is
not" below. `0008_brand_and_product_search_vector` is purely additive
(`Brand`, `Product.brand`, `Product.search_vector` + its GIN index) — no data
migration, nothing to trap here.

## What it is *not* — earlier docs described these; they do not exist

No embeddings. No characteristics JSONB. No `ImportJob`. No
`CharacteristicMutationJob`. No pgvector usage anywhere in the Python code. If
you find a reference to any of these, it is stale documentation, not code you
haven't found yet.

## Sync path — `sync_product_from_pim(pim_id, data=None)` (`services/pim_sync.py:101-152`)

`pim_id` here is a **PMP id** (see above), not a PIM `Product` id.

- **Local row lookup** (`:120-130`): the `Product` already holding `pim_id` →
  else the `Product` whose `number` equals the PMP's `number` and whose
  `pim_id` is still `NULL` adopts it → else a new `Product(number=...)`.
- **`data`** is the PIM `Product` reached through the PMP's `productId`
  (`_fetch_pim_product`, `:34-36`), fetched unless passed in.
- **Writes:** `name`, `raw_data`, `brand` (via `_ensure_pim_brand`,
  `:81-98` — matched on `brandId`, never `brandName`, for the same
  fork-on-rename reason as the `Brand` model itself; updates the local
  `Brand.name` in place when PIM's `brandName` changed), categories (via
  `categoriesIds` → `_ensure_pim_category`), then `rebuild_search_vector()`
  (`:151`, **after** `save()` — the rebuild does an `update()` by `pk`, which
  a brand-new row doesn't have yet). **Never `number`** — PIM staff can link a
  PMP to a PIM `Product` numbered differently from our local sku, and
  `number` is the local match key, not PIM's.
- **PMP with no `productId` yet:** only the link (`pim_id`/`number`) is
  saved; `name`/`raw_data`/`brand`/`categories` are left alone
  (`test_link_without_product_id_saves_the_link_only`).
- **One fetch of the link, not two:** `link` is fetched once and reused
  (`:120-135`) whether it's needed for matching, for `productId`, or both. A
  resync of a row that **already holds `pim_id`**, with `data` supplied,
  makes zero PMP calls (`test_resync_updates_existing_row_and_never_touches_number`
  asserts `fetch_link.assert_not_called()`) — but a not-yet-linked row still
  needs one `_fetch_pim_link` call even with `data` supplied, purely to learn
  the `number` it matches on.
- **Fetches happen before any write**, so a failed PIM fetch leaves no
  half-made `Product` row (`test_failed_link_fetch_leaves_no_row`).
  `_ensure_pim_category`/`_ensure_pim_brand` can still create rows before
  `product.save()` runs.
- `IntegrityError` still propagates uncaught: a new `Product` whose `number`
  another `Product` already holds under a different `pim_id`.
- **`or None`, two fields, two different reasons:** `number = link.get('number')
  or None` (`:126`) is still constraint-driven (Postgres treats `NULL`s as
  distinct in a unique index but `''` as equal — coercing to `''` would let
  the first numberless `Product` save and `IntegrityError` every one after
  it). `product.name = data.get('name') or None` (`:140`) is **not** —
  `name` stopped being unique (see above) — it's now just convention
  (`__str__` reads `f'{number} — {name}'`); tests assert the `None`, not `''`.
- **Callers.** `product/tasks.py:17-22`
  (`sync_product_from_pim_task`, via `execute_locked_task`, per-`pim_id`
  lock) wraps the function as a task but nothing dispatches that task
  (`.delay()`/`.apply_async()`) — the production caller goes through the
  plain function instead, from inside `sync_products()` (below). The other
  caller is the retiring-stack `supplier_feed` create-product endpoint
  ([[retiring_stack]] owns it) — expects a PMP id in its request body.
- **Tests:** `product/tests/test_pim_sync.py` mocks `_fetch_pim_link` and
  `_fetch_pim_product` at two separate seams (`LINK_PATCH`/`PRODUCT_PATCH`),
  plus a `PimClientWiringTests` class that patches only `SiteAPI.get` to
  confirm those two functions build the right `Entity`. Brand behaviour:
  `test_brand_is_created_from_brand_id_and_linked`,
  `test_brand_is_matched_on_id_so_a_rename_does_not_fork_it`,
  `test_product_without_brand_id_keeps_brand_null`.
  `test_sync_rebuilds_the_search_vector` guards the post-save rebuild.

### Backfilling content in production — `product.backfill_products_from_pim`

`product/tasks.py` also has a full pipeline for the third stage (content,
after `reindex_pim_ids` has assigned `pim_id`s): `backfill_products_from_pim_task`
finds unsynced pks via `unsynced_products()`/`iter_unsynced_product_pk_batches`
(`services/pim_sync.py`, "unsynced" = `pim_id` set, `raw_data={}`) and, per
batch, uses `dispatch_after_commit()` — not `.delay()` — to hand off to
`sync_products_batch_task`, for the same reason `reindex_pim_ids` does (its
own transaction can still roll back). That batch task runs with
`atomic=False` (it's on the network per-product and sleeps between calls) and
calls `sync_products(pks)`, which calls the **plain** `sync_product_from_pim`
function per pk (not the Celery task) and tolerates individual failures —
a failed row just stays eligible for the next pass (`test_failed_rows_stay_eligible_for_the_next_run`,
`product/tests/test_backfill.py`). **Not in `CELERY_BEAT_SCHEDULE`**
(`price_manager/settings/celery.py`) — unlike `reindex_pim_ids`, which runs
nightly, this has to be triggered manually, same `manage.py run_task
product.backfill_products_from_pim` pattern as the deploy note above.

### The phantom-field trap (fixed; the shape can recur)

`sync_product_from_pim` used to write `product.category_path = ...` before
`save()`, but `category_path` was never a real field — Django's `save()`
silently ignores assignment to a non-field attribute, so the write was a
no-op every sync. Both the helper and the assignment are gone. There is
**no** denormalised category-path column, deliberately: PIM's payload carries
no path string (only `categoriesIds`), so a path must be derived from the
local MPTT tree via `Category.get_ancestors()` — the `categories` M2M is the
source of truth. If something needs a path string, derive it at read time.

## Tests — re-fetch, don't trust the returned instance

`test_pim_sync.py` (`SyncProductFromPimTests`) asserts via
`Product.objects.get(pk=product.pk)`, not on the instance
`sync_product_from_pim` returned — that's why the phantom-field bug above
went undetected as long as it did. It's `Product.objects.get(...)`, not
`refresh_from_db()`: a fresh instance carries only real columns, while
`refresh_from_db()` leaves stray non-field attributes on the existing
instance intact and would let the same class of bug pass silently again.
`test_migration_0007.py` runs the migration's `RunPython` function directly
against ORM-created rows inside a normal `TestCase` — the only place its
filters meet real data (CI's DB is otherwise empty).

## The product page `/products/` — traps, all found on real data

`ProductFilter` (`filters.py`), `ProductTable` (`tables.py`), `ProductPage`
(`views.py`), `product/list.html` + `partials/`. PR #197 redesigned the
layout (sticky filters sidebar, compact table, offcanvas on mobile) but the
underlying mechanisms below are unchanged and still verified against current
line numbers. Every trap below passed a green suite and was caught only by
measuring on the prod snapshot or driving the page in a browser.

- **`SearchRank(F('search_vector'), …)`, never `SearchRank('search_vector', …)`**
  (`filters.py:42-57`). With a string, Django re-tokenizes the stored tsvector
  as text on every row with the default config, bypassing the GIN index.
- **Rank order needs `nulls_last=True`** (`filters.py:100-114`, `ranked()`).
  `'-rank'` compiles to `ORDER BY rank DESC`, and Postgres puts NULLs *first*
  on DESC. Products with no PIM data have no vector, so their rank is NULL,
  and they filled all of page 1 on every search measured.
  `test_full_text_match_ranks_above_a_supplier_name_only_match` guards this.
- **Search is a UNION, not an OR** (`matching_product_pks`, `filters.py:60-97`).
  Vector, `number__icontains` and the MainProduct-name `Exists` are each
  cheap alone; OR'd together Postgres can't combine the GIN scan with the
  subquery and scans everything (622ms vs 263–586ms measured).
- **The category facet needs `select_related` to depth 5**
  (`CATEGORY_LABEL_DEPTH`, `filters.py:131-135,175`). `Category.__str__`
  recurses through `self.parent`: 1,567 queries / 1.6s on the real tree vs 1
  query / 36ms.
- **The category facet is a tree, not a checkbox list**
  (`product/partials/category_tree_field.html` + `category_tree_node.html`,
  `{% recursetree %}`, shared — see below). A flat list was 668 rows with
  paths up to 126 chars. Filtering to "has products" doesn't help: 633 of 668
  categories do (measured).
- **`ProductPage.get_template_names()` must return the table fragment for
  HTMX** (`views.py:64-80`). Filter and search both `hx-get` back to
  `products`, not a separate fragment endpoint — so `hx-push-url` keeps the
  address bar correct. Without the `request.htmx` branch the whole page
  renders inside `#products-table`.
- **The search widget needs an explicit `id='products-search'`**
  (`filters.py:167`). Django's default `id_search` isn't what
  `hx-trigger`/`hx-include` select on.
- **`self.data` is not always a QueryDict** — `selected_values()`
  (`filters.py:26-39`) handles a plain dict, since django-filter 25.1 only
  swaps a *falsy* `data` for an empty `QueryDict`. [[supplier_product_manager]]'s
  `SupplierProductFilter` calls `self.data.getlist()` bare and raises
  `AttributeError` from `__init__` if built from a plain dict.
- **Search is shared, not copied.** `filters.py` exposes
  `matching_product_pks`, `ranked`, `search_rank`, `category_with_descendants`
  and `selected_values` at module level; [[main_product_manager]]'s
  `MainProductFilter` (cart's product picker) imports and reuses every one
  (`main_product_manager/filters.py:9-16`). Change search here and the cart
  changes with it — that is the point.
- **`price_from`/`price_to` filter on `MainProduct.prime_cost`** via the same
  `_with_main_product(Exists(...))` helper as `supplier`/`available`
  (`filters.py:201-211,272-295`) — added with the PR #197 redesign, no
  surprise mechanism, just note it exists if you're looking for "cost" and
  don't see a field on `Product`.
- **Column preferences (`columns.py`) are cached per user under
  `product_page:columns:user:<id>`** (`:94-95`) — a separate key from the
  supplier-detail page's `supplierdetail:selected_columns:user:<id>`
  ([[supplier_product_manager]]). `normalize_columns` keeps catalog order and
  turns an empty choice into `DEFAULT_COLUMNS`, never zero columns. The
  picker's hidden empty `columns=` (`columns_picker.html:32`) is there so
  that «снял всё» still sends the key: with no `columns` in the request the
  view loads the saved choice instead of saving (`views.py:92-96`).

### Rendering — found by driving the page in a browser

- **The filter partials are shared: an edit lands on every screen that
  renders them.** `category_tree_field.html`/`category_tree_node.html`:
  `product/filters.py:175` and `main_product_manager/filters.py:117,134`
  ([[main_product_manager]]'s cart picker and «Привязать из ГП»).
  `core/includes/checkbox_field.html`: `product/filters.py:337,339`,
  `main_product_manager/filters.py:118-119,138,142` (`:118-119` render its
  `#checkboxes` partialdef on the OOB path — see [[core]]) and
  `supplier_product_manager/filters.py:108`. `radio_field.html` emits the
  same classes (`:50,54`) via `CustomRadio('supplier')` in the «Добавить
  товар» form (`main_product_manager/forms.py:43`). The tree needs an
  ancestor-closed queryset — `recursetree` on an orphaned node raises, a 500
  in the cart modal — so `MainProductFilter` adds
  `get_ancestors(include_self=True)` (`main_product_manager/filters.py:194-205`);
  `ProductFilter` passes the whole tree. The tree's root id `div_<auto_id>`
  is also the OOB-swap target for the stripped render
  (`main_product_manager/filters.py:117`): rename it and the refresh
  silently stops.
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
  **only** at `list.html:137,147,209` — the old main page carried the rules
  and Phase 2b-1 deleted it, leaving the shared markup with none. The tree
  keeps its own inline `max-height` (`category_tree_field.html:24`); the
  «Добавить товар» modal (`#modal-container`, `list.html:725`) sits outside
  `.products-sidebar` and needs none of this. Unbounded facet list? Check the
  page still carries these rules before debugging the markup.
- **A multi-line `{# … #}` is not a comment in Django — it renders as text.**
  The lexer matches `{#.*?#}` without `DOTALL`, so a `{#` whose `#}` is on a
  later line is literal, and any tag inside it executes. Both
  `category_tree_node.html` (leaf branch, now `{% comment %}` at `:33-41`)
  and `product/partials/table.html` (top-of-file note, now `{% comment %}`
  at `:2-13`) had this. Guarded by
  `test_filter_fragment_does_not_leak_template_comments`
  (`test_views.py:185-200`) and
  `test_fragment_does_not_leak_template_comments_into_the_response`
  (`test_views.py:158-167`).
- **The name column cannot sort — by construction — and there is no sort by
  brand.** `ProductTable.display_name` is `orderable=False` (`tables.py:61`):
  `Product.display_name` is a `@property`, not a column, so the database
  can't order by it (a sortable name would need an annotation reproducing the
  fallback — `Coalesce`, untried). Sort links come from `column.orderable`
  (`partials/table.html:33`): only `number`, `supplier_count`, `total_stock`
  sort. Brand and categories render as a `brand · category · …` line under
  the name (`tables.py:139-144`), not columns — hence no brand sort.
  `_base_queryset` (`views.py:23-32`) keeps `select_related('brand')` and the
  categories prefetch for that cell; drop either and it's N+1, unguarded by
  `assertNumQueries`.
- **Known gap, not fixed — the mobile filter drawer stays open after a
  checkbox tick.** Below `lg` the filters sit in an offcanvas
  (`#products-filters`, `list.html:634`) closed only by a `submit` listener
  on `#product-filter` (`list.html:837-842`), i.e. by «Применить». A tick
  auto-applies via `hx-trigger` `change delay:600ms` (`filters.py:315`),
  which fires no `submit`, so the drawer stays open over the refreshed
  results.

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
- ~64% of `Product`s have no PIM category (coverage above). All of them are one
  «Без категории» group at the tail, ordered by stored `name`, which unsynced rows
  may lack.
- Header paths come from the categories prefetch, now
  `Prefetch(..., Category.objects.select_related(CATEGORY_LABEL_DEPTH))` in
  `_base_queryset`. Walking `parent` without it is a query per level.
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

## Filling the mirror from PIM (dev-only) — `load_pim_mirror`

`services/pim_sync.py`: `sync_category_tree_from_pim()` and
`load_products_by_number()`, wrapped by `manage.py load_pim_mirror`. This is
distinct from the production `backfill_products_from_pim` pipeline above —
this one is bulk/oneshot and matches by `number` across the whole PIM
catalogue rather than walking already-assigned `pim_id`s one at a time.

- **Read-only against PIM.** It exists because `reindex_pim_ids` (the
  production path in [[main_product_manager]]) *creates* `PriceManagerProduct`
  records in PIM, which must never happen from a dev or snapshot database.
- **`sync_category_tree_from_pim` is the fix for stale categories.**
  `_ensure_pim_category` returns early when a category exists and never
  updates `name` or `parent`, and only runs when a product happens to
  reference that category, so it can never see a rename on an untouched
  branch. The tree sync walks PIM's whole list; it re-parents with MPTT
  `move_to`, because a plain `save()` leaves `lft`/`rght`/`level` broken.
- **PIM list mode omits fields silently.** Without an explicit `select`,
  `Product` rows come back with no `categoriesIds` and no `description` at
  all — not empty, absent. Use `PRODUCT_SELECT`.
- **PIM facts measured on the live API:** 178,605 products, 668 categories in
  15 roots, 6 levels deep. `linkedWith` on >100 category ids returns
  `414 URI Too Long`. PIM does **not** expand a category to its descendants
  (a root alone returns 0 products), so the MPTT expansion in
  `categories_method` is required, not an optimisation.
- **Coverage is ~36%, and that is real.** 55,281 of 155,087 Products match a
  PIM number. Whitespace/case/prefix-suffix stripping do not meaningfully
  close it. The old `mainproduct.pim_id` values in the dump are dead ids from
  an earlier generation of PIM records — every one returns 404.
- **Network flakes are normal over a 50-minute pass** (TLS EOF, DNS
  `Name or service not known`); page fetches retry 6 times (~1 min, see
  `_PAGE_RETRIES`). Use `--start-offset` to resume and `--vectors-only` to
  finish just the vectors.

## Status boundary — the subtle part

`CLAUDE.md` still lists `product` among the retiring five, with an exception
for the PIM-mirror reconnection. **The product shift has since gone further
than that exception described:** `Product` is now the root of search and
filtering, with its own page. Work that serves that shift — decided by the
user and specified in `.claude/shift-to-product-brief.md` — is in scope.
Growing `product` into something *independent of PIM and the legacy stack* is
still not. It remains the only one of the five with no `api/` package — not
mounted in `api_urls.py`. Its siblings are covered by [[retiring_stack]].
