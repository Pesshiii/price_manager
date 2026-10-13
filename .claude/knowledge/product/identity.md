---
title: Product identity — the (number, brand) pair
summary: Why a Product is unique only by a branded (number, brand) pair, where a row's and a Product's brand come from, resolve_product, the supplier-brand adoption pass, PIM's brand rules, and what step 3 left undone.
code: price_manager/product/models.py, price_manager/product/migrations/0021_product_number_brand_uniq.py, price_manager/main_product_manager/utils.py, price_manager/product/services/brands.py, price_manager/product/services/pim_sync.py, price_manager/product/services/sets.py, price_manager/product/forms.py
---
# Product identity — the (number, brand) pair

Step 3 of «товар = бренд + артикул» (2026-10-13). The policy and the later
steps are in `.claude/shift-to-product-brief.md` §0.6. The repo-wide rule is in
`CLAUDE.md`. This topic covers the mechanism and its traps.

## The constraint

`0021` swapped the unique `Lower(number)` for
`UniqueConstraint(Lower('number'), 'brand', condition=brand IS NOT NULL)`. The new
constraint is strictly weaker, so the migration is schema-only and safe on
production data. It also adds a plain `Index(Lower('number'))`: the partial
unique index covers no brandless row, and the old unique index was what served
every `Lower(number)` lookup.

**Brandless Products sharing a number are different products until they get a
brand.** The user decided this. A number alone therefore names no Product.
Nothing may "find the Product of this sku" any more without a brand.
`_link_to_local_product` and `link_to_local_products` were deleted for that
reason, and `get_pim_data_for_product` no longer links on the render path.

## Where a brand comes from

- **A ГП row** has no brand field. A price-list row's brand is
  `SupplierProduct.brand`, resolved from the brand column
  (`row_brand_subquery`/`row_brand_id`; `SupplierProduct.main_product` is
  unique, so there is at most one). A hand-made row's brand is the «Бренд» picker
  in the «Строка ГП» modal (`MainProductForm.brand`, not a model field). The
  picker is disabled for price-list rows, set rows, and rows added from a card.
- **A Product** takes PIM's brand when PIM has one. Otherwise it takes the
  brand its suppliers agree on.

## Writing: `resolve_product(sku, brand_id, name)`

With a brand, the pair is found (`iexact`) or created, and an `IntegrityError`
re-reads it. Without a brand, **every call creates a new Product**. The callers
are `ensure_product` (admin, admin import; brand defaults to the row's
price-list brand), `MainProductCreate` (the picker; a card-preset product wins),
and `MainProductUpdate`. The update view moves the row when its sku or brand
changes, using the price-list brand for a price-list row. The create view
tells the user when a brandless row lands next to other Products with its
number.

`link_unlinked_main_products` follows the same rule in bulk, for copy-to-main
and the nightly reindex. Each chunk is locked with `select_for_update(of=self)`,
so a row moved by hand meanwhile is skipped and a brandless row never leaves
an orphan Product. Lowercasing comes from Postgres (`Lower('sku')` in the same
query), never from Python's `.lower()`.

**Consequence: a new row never joins an existing brandless Product.** The user
put it this way: a row that is new for its supplier is a separate product. An
existing row whose supplier later names a brand reaches its Product through the
adoption pass below.

## The adoption pass — `adopt_supplier_brands()` (`services/brands.py`)

A brandless Product gets brand X when all of these hold. This is the user's
«да, если нет спора».
- at least one of its rows' price-list rows resolves to X, and none resolves to
  another brand;
- none of its rows has a spelling that is still **waiting** in «Бренды». An
  unresolved spelling is a claim too. An ignore-alias («Без бренда») is not;
- no other Product holds (number, X). Of brandless twins competing for one
  pair, the lowest pk wins and the rest stay brandless (`taken`).

The pass runs the whole catalogue as task `product.adopt_supplier_brands`
(default queue, locked). `apply_brand_resolution` dispatches it after commit,
so it follows every import, every alias change in the window and the nightly
`sync_brands`. A `--dry-run` backfill rolls back and dispatches nothing. A run
skipped by the lock is caught up by the next one.

**The search vector is appended to, not rebuilt.** One `UPDATE … SET
search_vector = COALESCE(search_vector,'') || setweight(to_tsvector('russian',
brand), 'B')` runs per chunk. A rebuild costs one query per Product, and the
first pass brands tens of thousands of them.

**The pass never touches the PIM link.** A Product pushed while brandless
already has a PMP. That PMP was pushed without `productId` if PIM had only
branded cards for the number. Nothing re-searches it once the Product gets a
brand: reindex only pushes Products with `pim_id` NULL. Clearing `pim_id` would
re-push and fix it, because the upsert matches on `platformID`, but on the
first pass that means tens of thousands of searches on the `pim` queue. That
call is a deliberate command, not a side effect.

## PIM's brand — `apply_pim_product` → `_pim_brand_for`

- PIM has no brand: the local brand stays. A sync no longer clears it.
- The local brand did not come from PIM, and PIM names another one: the local
  brand stays and the conflict is logged. "Came from PIM" means it equals the
  `brandId` in the previous `raw_data`. So a brand PIM gave once follows PIM's
  later changes.
- Another Product already holds (number, PIM's brand): the brand is not set and
  the conflict is logged. Name, `raw_data` and categories are still written.
  The fix is manual: move the ГП rows and delete the empty Product.

## PIM search and push

- `_search_pim_product_id(number, brand_pim_id)` selects `brandId` (list mode
  returns it only when it is selected) and matches the brand on our side. A
  branded Product matches only its brand's card. A brandless Product matches
  only a brandless card, because binding it to a branded card by number would
  guess its brand.
- `PriceManagerProduct.number` is not unique in PIM since 2026-10-13. Only
  `platformID` is (re-read from `/api/metadata`). `_take_over_pim_link` was
  deleted: a rejected push stays rejected (`PimScanError`). Taking a PMP over by
  number would now trade one PMP between Products that share a number, every
  night.
- `sync_product_from_pim` for a PMP that no Product holds: `_adopting_product`
  tries `platformID` (our pk) first. It falls back to the number only when
  exactly one Product without a `pim_id` has it.

## Elsewhere

- **Sets** (`services/sets.py` `_candidates`/`_pick`): the number fallback never
  takes a Product whose brand contradicts the PIM card's `brandId`. An empty
  brand on either side is no contradiction, since it may simply be unfilled.
  `_pick` prefers the same brand. A set mirrored before is recognised by its
  PIM id in `raw_data`, the same way a PMP link is. Without that, a set whose
  brand changes in PIM would have its number+brand search miss our set
  Product and create a second one.
  `_fetch_pim_products_brief` selects `brandId`.
- **The card form** (`ProductForm.clean`) refuses a taken pair. The error links
  to the holder (`format_html`; the template prints it unescaped). Brandless
  duplicates pass.
- **`merge_brands`** raises `BrandMergeConflict` when the loser and the winner
  both have a Product with the same number. Moving the loser's Product would
  create a second copy of the pair. The window shows the message and changes
  nothing.
- **`load_pim_mirror`** (dev only) matches only numbers that a single local
  Product holds.

## Not done in step 3

The number is still the sku with the supplier prefix or suffix, not the clean
article. Existing multi-supplier brandless Products were not split. Products
sharing a PIM `productId` were not merged. All of that is the data step,
together with `MainProduct.link_source`, search over `MainProduct.sku` and
Satu's «Код_товара», which can now repeat.
