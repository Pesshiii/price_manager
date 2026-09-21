# product

**Read this before assuming anything about `product`.** It is the one app whose
status recently inverted, and stale mental models of it are actively wrong.
PR #184 (merged, `21175bb`) changed what `Product.pim_id` *means*, and the
product-shift Phase 1 (2026-09-19) made `Product` the root of search and
filtering, with its own page at `/products/`. Re-verify anything below that
predates either one if this file looks old. The design and every decision
behind it are in `.claude/shift-to-product-brief.md`.

## What it is *now*

A plain **PIM-linked mirror**, being deliberately recreated and reconnected to
the live legacy stack — treat anything here as in-motion; check
`git log -- product/` if something surprises you.

`product/models.py` — read the whole thing:
- `Category(MPTTModel)` — `parent`(PROTECT) / `name` / `slug` / `pim_id`,
  unique constraint on `(parent, name)`, `order_insertion_by = ['name']`.
  `save()` auto-generates a unique `slug` via `slugify(allow_unicode=True)`
  with a `-2`, `-3` … suffix loop. **`__str__` recurses through `self.parent`**
  — see the N+1 trap below.
- `Brand` — `pim_id` (unique, PIM `brandId`), `name`. **Keyed on the id, never
  the name**: a PIM rename would otherwise fork one brand into two. No alias
  layer by design — `supplier_manager.ManufacturerDict` solved that for supplier
  names and has 0 rows in prod.
- `Product` — `pim_id` (nullable, unique — see next section for what it now
  identifies), `number` (unique, nullable, the local match key =
  `MainProduct.sku`, never overwritten from PIM), `name` (**not** unique),
  M2M `categories`, FK `brand` (nullable — PIM returns `brandId` as a
  **scalar**, hence FK not M2M), `raw_data` JSON, `search_vector` + GIN
  (`product_search_vector_gin`, `config='russian'`), timestamps.
  `ordering = ['-updated_at']`.
- `Product.display_name` — `name`, else the first linked MainProduct's name,
  else `number`. Needed because `name` comes from PIM and ~64% of Products have
  no PIM counterpart at all.
- `Product._build_searchvector()` builds **only from `raw_data`** — no network
  call. That is the defect `MainProduct._build_searchvector()` has, and the
  reason search moved here. Joins with `' '`, not `''`: the MainProduct version
  glued category names into one token, so neither word was searchable.

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
  left `NULL` (`main_product_manager/utils.py:663`). Don't assume a `Product`
  with data came from `sync_product_from_pim` or `0005`'s seed.
- `name` **stopped being unique** (it was, briefly, under `0006` — see below):
  several local `Product`s can point at one PIM `Product` (PIM `Product`
  hasMany `priceManagerProducts`), and PIM's own metadata (`GET
  /api/metadata`) doesn't declare `Product.name` or `Product.number` unique
  either. The open question this file used to carry about duplicate PIM names
  is resolved by that check — delete, don't leave standing.
  (`test_name_is_not_unique`, `product/tests/test_models.py`.)

## Migration `0007_product_pim_id_is_price_manager_product` — the meaning-change migration

This is now the worked example for tightening/loosening a constraint on
`Product` against a populated database (`0006`, below, used to be it — its
outcome is reversed here, but the step-ordering lesson is the same shape,
plus a cross-app dependency wrinkle):

1. `AlterField pim_id → nullable` (`:55`) first — the following step can't
   write NULLs into a NOT-NULL column.
2. `RunPython(reset_pim_ids)` (`:27`) nulls **every** `pim_id` unconditionally
   — the old values are PIM `Product` ids, meaningless under the new schema.
   The next `reindex_pim_ids` re-derives them by `number` search.
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
dependency, not just an ordering convenience. Not reversible on data (reverse
is noop); reversing the schema hits `NOT NULL` on `pim_id` while unpopulated
rows exist. **CI migrates an empty database**, so this data step never meets
a row there — `product/tests/test_migration_0007.py`
(`ResetPimIdsTests.test_nulls_every_pim_id_and_deletes_only_unreferenced_placeholders`)
is the only coverage, and it works by importing the migration module via
`importlib` (its name starts with a digit, can't `import` normally) and
calling `reset_pim_ids(django.apps.apps, None)` directly against real rows.
**Deploy note:** run `manage.py run_task reindex_pim_ids` right after
migrating — no PIM data shows on any `Product` until it re-pushes.

`0005_seed_products_from_main_product_pim_ids` bulk-creates a bare `Product`
per then-existing `MainProduct.pim_id` (before that field became the
`MainProduct.product` FK) and never touches `name`, so every seeded row lands
with `name=''` — and because `0005` seeds **zero rows against CI's empty test
database**, that populated-database shape is invisible to CI. This is the
same blind spot `0007`'s dedicated migration test exists to cover, just one
migration earlier. `0006_alter_product_name` existed to add a unique
constraint on `name` despite that (nullable → `RunPython` turning `''` into
`NULL`, raising with the offending values on a duplicate rather than a bare
`IntegrityError` → `AlterField unique=True`); `0007` removes the constraint
again (see above) but repeats the exact same three-step shape, because the
same CI-blind-spot risk applies to any schema change whose correctness
depends on cleaning up populated rows first. `0002`/`0003` briefly carried
embedding/characteristics-era fields (`sku`, `characteristics`,
`embedding_text_hash`, …); `0003` removes every one of them — see "What it is
not" below.

## What it is *not* — earlier docs described these; they do not exist

No embeddings. No characteristics JSONB. No `ImportJob`. No
`CharacteristicMutationJob`. No pgvector usage anywhere in the Python code. If
you find a reference to any of these, it is stale documentation, not code you
haven't found yet.

## Sync path — `sync_product_from_pim(pim_id, data=None)` (`services/pim_sync.py:65-111`)

`pim_id` here is a **PMP id** (see above), not a PIM `Product` id.

- **Local row lookup** (`:85-94`): the `Product` already holding `pim_id` →
  else the `Product` whose `number` equals the PMP's `number` and whose
  `pim_id` is still `NULL` adopts it → else a new `Product(number=...)`.
- **`data`** is the PIM `Product` reached through the PMP's `productId`
  (`_fetch_pim_product`, `:18`), fetched unless passed in.
- **Writes:** `name`, `raw_data`, categories (via `categoriesIds` →
  `_ensure_pim_category`). **Never `number`** — PIM staff can link a PMP to a
  PIM `Product` numbered differently from our local sku, and `number` is the
  local match key, not PIM's.
- **PMP with no `productId` yet:** only the link (`pim_id`/`number`) is
  saved; `name`/`raw_data`/`categories` are left alone
  (`test_link_without_product_id_saves_the_link_only`).
- **One fetch of the link, not two:** `link` is fetched once and reused
  (`:84-97`) whether it's needed for matching, for `productId`, or both. A
  resync of a row that **already holds `pim_id`**, with `data` supplied,
  makes zero PMP calls (`test_resync_updates_existing_row_and_never_touches_number`
  asserts `fetch_link.assert_not_called()`) — but a not-yet-linked row still
  needs one `_fetch_pim_link` call even with `data` supplied, purely to learn
  the `number` it matches on (`:87`).
- **Fetches happen before any write**, so a failed PIM fetch leaves no
  half-made `Product` row (`test_failed_link_fetch_leaves_no_row`).
  `_ensure_pim_category` can still create `Category` rows before
  `product.save()` runs, same as before this branch.
- `IntegrityError` still propagates uncaught: a new `Product` whose `number`
  another `Product` already holds under a different `pim_id`.
- **Callers:** `product/tasks.py:8-13` (`sync_product_from_pim_task`, routed
  through `execute_locked_task` with a per-`pim_id` lock) — grepped clean of
  any dispatcher (`.delay()`/`.apply_async()`/beat schedule) anywhere in the
  repo this session, so today it's reachable only by calling the task
  directly; treat that as a snapshot, not a guarantee, if it matters. The
  other caller is the retiring-stack `supplier_feed` create-product endpoint
  ([[retiring_stack]] owns it) — it now expects a PMP id in its request body,
  same meaning change as everywhere else.
- **Tests:** `product/tests/test_pim_sync.py` mocks `_fetch_pim_link` and
  `_fetch_pim_product` at two separate seams (`LINK_PATCH`/`PRODUCT_PATCH`),
  plus a `PimClientWiringTests` class that patches only `SiteAPI.get` to
  confirm those two functions build the right `Entity`.

### The `or None` convention — two fields, two different reasons now

`pim_sync.py:90` writes `number = link.get('number') or None`: `number` is
still unique, and Postgres treats `NULL`s as distinct in a unique index but
`''` as equal, so coercing a missing number to `''` would let the first
numberless `Product` save and `IntegrityError` every one after it. This one
is still constraint-driven — keep it `or None`.

`pim_sync.py:104` writes `product.name = data.get('name') or None`, but
`name` **is no longer unique** (see above), so this is no longer protecting
against a uniqueness collision. It's now just convention — `__str__` reads
`f'{number} — {name}'`, and `test_products_without_name_coexist` /
`test_link_without_product_id_saves_the_link_only` both assert a missing name
is `None`. Don't cite uniqueness as the reason for this one anymore, but
don't drop it either — tests depend on the `None`, not `''`.

### The phantom-field trap (fixed; the shape can recur)

`sync_product_from_pim` used to write `product.category_path = ...` before
`save()`, but `category_path` was never a real field — Django's `save()`
silently ignores assignment to a non-field attribute, so the write was a
no-op every sync, and a fresh fetch's `.category_path` raised
`AttributeError`. Both the helper and the assignment are gone. There is
**no** denormalised category-path column, deliberately: PIM's payload carries
no path string (only `categoriesIds`), so a path must be derived from the
local MPTT tree via `Category.get_ancestors()` — the `categories` M2M is the
source of truth. If something needs a path string, derive it at read time;
don't reintroduce a stored field.

## Tests — re-fetch, don't trust the returned instance

`test_pim_sync.py` (`SyncProductFromPimTests`) asserts via
`Product.objects.get(pk=product.pk)`, not on the instance
`sync_product_from_pim` returned — that's why the phantom-field bug above
went undetected as long as it did. Note it's `Product.objects.get(...)`, not
`refresh_from_db()`: a fresh instance carries only real columns, while
`refresh_from_db()` leaves stray non-field attributes on the existing
instance intact and would let the same class of bug pass silently again.
Keep new assertions in this module on the re-fetched row.

`test_models.py` asserts on freshly-`.create()`d instances without a
re-fetch, but harmlessly — those are `IntegrityError`/uniqueness checks, not
attribute round-trips. `test_migration_0007.py` (`ResetPimIdsTests`) is a
third pattern: it runs the migration's `RunPython` function directly against
rows created via the ORM, inside a normal `TestCase` — see the migration
section above for why that's the only place its filters meet real data.

## The product page `/products/` — traps, all found on real data

`ProductFilter` (`filters.py`), `ProductTable` (`tables.py`), `ProductPage`
(`views.py`). Every trap below passed a green suite and was caught only by
measuring on the prod snapshot or driving the page in a browser.

- **`SearchRank(F('search_vector'), …)`, never `SearchRank('search_vector', …)`.**
  With a string, Django treats it as a text field to vectorize and emits
  `ts_rank(to_tsvector(search_vector::text), …)`: the stored tsvector is cast to
  text and re-tokenized on every row, with the default config instead of
  `russian`, bypassing the GIN index. Copied from [[main_product_manager]]'s
  `MainProductFilter.search_rank`, which had the same bug (now also fixed).
- **Rank order needs `nulls_last=True`.** `'-rank'` compiles to
  `ORDER BY rank DESC`, and Postgres puts NULLs *first* on DESC. Products with no
  PIM data have no vector, so their rank is NULL, and they filled **all 25 rows of
  page 1 on every search measured**, pushing every genuine full-text match off it.
  `test_full_text_match_ranks_above_a_supplier_name_only_match` guards this and is
  verified to fail on the old ordering. The rest of the suite never checked order,
  only membership.
- **Search is a UNION, not an OR.** Vector (36ms), `number__icontains` (41ms) and
  the MainProduct-name `Exists` (98ms) are each cheap. OR'd together Postgres
  cannot combine the GIN scan with the subquery and scans everything: 622ms for the
  filter alone and ~1.4s per page even with one result. As a UNION of `pk` sets
  it is 263–586ms end to end.
- **The category facet needs `select_related('parent__…')` to depth 5.**
  `Category.__str__` recurses through `self.parent`: 1,567 queries and 1.6s on the
  real tree, versus 1 query and 36ms. Same labels byte for byte.
- **The category facet is a tree, not a checkbox list.** 668 flat checkboxes with
  full paths up to 126 chars was unusable. `product/partials/category_tree_*.html`
  is a copy of `supplier_manager`'s MPTT accordion — a *copy*, because Phase 2
  retires that app. Showing only categories that have products does **not** help:
  633 of 668 do.
- **`ProductPage.get_template_names()` must return the table fragment for HTMX.**
  Filter and search both `hx-get` back to `products`; without the branch, the whole
  page is rendered inside `#products-table`. Don't "fix" it with a separate fragment
  endpoint: `hx-push-url` would then put the fragment's URL in the address bar.
- **The search widget needs an explicit `id='products-search'`.** Django renders
  `id_search`; `hx-trigger`/`hx-include` select on `#products-search`, and both
  silently matched nothing — search did nothing and every filter wiped the query.
- **`self.data` is not always a QueryDict** — `selected_values()` handles a plain
  dict. The old page's `MainPageFilter` still calls `.getlist()` directly and raises
  `AttributeError` in `__init__` if built from a dict.
- **Search is shared, not copied.** `filters.py` exposes `matching_product_pks`,
  `ranked`, `search_rank`, `category_with_descendants` and `selected_values` at
  module level, because [[main_product_manager]]'s `MainProductFilter` (the cart's
  picker) searches through `MainProduct.product` with exactly the same definition.
  Change the search here and the cart changes with it — that is the point.
- **Column preferences (`columns.py`) are cached per user under
  `product_page:columns:user:<id>`**, deliberately not the old page's key, whose lists
  name fields Phase 2b drops. `normalize_columns` keeps catalog order and falls back
  to `DEFAULT_COLUMNS`; an empty `columns=` in the request is an explicit "nothing",
  which is why the picker carries a hidden empty input.

## Filling the mirror from PIM — `load_pim_mirror`

`services/pim_sync.py`: `sync_category_tree_from_pim()` and
`load_products_by_number()`, wrapped by `manage.py load_pim_mirror`.

- **Read-only against PIM.** It exists because `reindex_pim_ids` (the production
  path in [[main_product_manager]]) *creates* `PriceManagerProduct` records in PIM,
  which must never happen from a dev or snapshot database.
- **`sync_category_tree_from_pim` is the fix for stale categories.**
  `_ensure_pim_category` returns early when a category exists and never updates
  `name` or `parent`, and it only runs when a product happens to reference that
  category, so it can never see a rename on an untouched branch. The tree sync walks
  PIM's whole list; it re-parents with MPTT `move_to`, because a plain `save()`
  leaves `lft`/`rght`/`level` broken.
- **PIM list mode omits fields silently.** Without an explicit `select`, `Product`
  rows come back with no `categoriesIds` and no `description` at all — not empty,
  absent. Use `PRODUCT_SELECT`.
- **PIM facts measured on the live API:** 178,605 products, 668 categories in 15
  roots, 6 levels deep. `linkedWith` on >100 category ids returns
  `414 URI Too Long`. PIM does **not** expand a category to its descendants (a root
  alone returns 0 products), so the MPTT expansion in `categories_method` is
  required, not an optimisation.
- **Coverage is ~36%, and that is real.** 55,281 of 155,087 Products match a PIM
  number. Whitespace (+400), case (+380) and prefix/suffix stripping do not close it.
  The old `mainproduct.pim_id` values in the dump are dead ids from an earlier
  generation of PIM records — every one returns 404.
- **Network flakes are normal over a 50-minute pass** (TLS EOF, DNS
  `Name or service not known`); page fetches retry 6 times (~1 min). Use
  `--start-offset` to resume and `--vectors-only` to finish just the vectors.

## Status boundary — the subtle part

`CLAUDE.md` still lists `product` among the retiring five, with an exception
for the PIM-mirror reconnection. **The product shift has since gone further
than that exception described:** `Product` is now the root of search and
filtering, with its own page. Work that serves that shift — decided by the
user and specified in `.claude/shift-to-product-brief.md` — is in scope. Growing
`product` into something *independent of PIM and the legacy stack* is still
not. It remains the only one of the five with no `api/` package — not mounted
in `api_urls.py`. Its siblings are covered by [[retiring_stack]].
