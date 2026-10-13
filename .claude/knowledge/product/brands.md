---
title: Brands — PIM mirror, supplier spellings, the «Бренды» window
summary: How a supplier's brand text becomes a PIM brand (BrandAlias, implicit name key), how a row with no claim inherits its Product's brand, the full brand-list sync, «Создать в PIM», merge of brands gone from PIM, and the traps.
code: price_manager/product/services/brands.py, price_manager/product/brand_views.py, price_manager/product/models.py, price_manager/product/views.py, price_manager/product/services/pim_sync.py, price_manager/supplier_product_manager/functions.py, price_manager/supplier_product_manager/migrations/0021_supplierproduct_brand_from_product.py
---
# Brands — PIM mirror, supplier spellings, the «Бренды» window

Step 1 of «товар = (бренд, артикул)» (2026-10-12). It reopens D3 and D11 of the
product-shift brief; the reasons and the later steps are in its §0.6.

## Three brand fields, three meanings

- `product.Brand` mirrors a **PIM** brand (`pim_id` = brandId, not null).
- `SupplierProduct.brand_name` holds the **supplier's text**, raw from the file
  (`Link` key `brand_name`).
- `SupplierProduct.brand` is that text **resolved** to a PIM brand, when the
  supplier names a brand. When it names none, it is the brand of the row's
  Product (next section). It is not purely the supplier's claim.
- `Product.brand` is PIM's (`apply_pim_product`), or failing that, since step 3,
  the brand the Product's suppliers agree on (`adopt_supplier_brands`, which
  every `apply_brand_resolution` dispatches after commit). It is half of the
  Product's identity — see [[product/identity]].

## A row with no claim inherits its Product's brand

Since 2026-10-13. A row's brand is half of its (number, brand) pair, and
`row_brand_id`/`row_brand_subquery` (`main_product_manager/utils.py`) read
`SupplierProduct.brand`. Before the rule, a price-list row of a supplier without
a brand column, sitting on a branded Product, moved to a **new brandless**
Product when its sku was edited in «Строка ГП», and renumbering would have lost
the brand the same way. The user chose to keep the brand on the price-list row
only (no `MainProduct.brand` field) and to inherit at resolution, over a stored
flag or simply not clearing.

`apply_brand_resolution` sets `brand` by the spelling:

- `brand_name` resolves to a PIM brand X: `brand` = X. The supplier's claim.
- **No claim**: `brand_name` is NULL, or the spelling means «no brand» (an
  ignore-`BrandAlias` with brand NULL, or a separators-only spelling with an
  empty key). `brand` = the brand of the row's ГП's Product. No ГП, no Product
  or a brandless Product: NULL.
- An unresolved spelling (waiting in «Бренды»): NULL. It stays in the queue.

**Trap, now removed.** `apply_brand_resolution` used to start by clearing
`brand` on every `brand_name IS NULL` row. That wiped any brand on such rows on
every `resolve_all` (nightly `sync_brands` 02:30, every alias add or delete) and
on every import with a brand column. It now inherits instead. The ignore branch
inherits too, instead of clearing.

Mechanism. `_inherit(rows)` runs two `UPDATE`s, only on rows whose brand
differs: one clears `brand` where the Product has none, one sets it from a
correlated `Subquery`. It takes **no-claim rows only**. The public
`inherit_product_brands(rows, index=None)` filters any queryset to its no-claim
rows first (one `distinct` query of the spellings plus `BrandIndex.lookup`),
then calls `_inherit`. Pass `index` when one is at hand.

**Immediate refresh points** (everything else waits for a resolution):

- `_relinked` in `product/views.py`: a ГП row moved or attached to another
  Product, so its price-list row takes the target's brand.
- `ProductUpdateView.form_valid`, when `brand` is in `changed_data`.
- `apply_pim_product` (`services/pim_sync.py`), when `product.brand_id` changed.
- `adopt_supplier_brands`, after each adopted chunk, and once at the start (see
  [[product/identity]]).

**Lag that remains, by design.** A Product brand changed by any other path
(the admin, dev-only `load_pim_mirror`) reaches its rows at the next
resolution: the nightly `sync_brands` → `resolve_all`, or the next adoption
pass. `merge_brands` moves both sides together, so it needs no refresh.

**One-off migration.** `supplier_product_manager.0021_supplierproduct_brand_from_product`
sets `brand` = the Product's brand on no-claim rows with `brand` NULL.
Reverse clears `brand` on no-claim rows, which never had one before the rule.
It inlines a frozen copy of `brand_key` and treats «no brand» as an ignore-alias
key or an empty key, mirroring `BrandIndex.lookup`, so it does not depend on app
code. Migrations deploy by hand (`deploy/README.md`): this one runs with the
workers stopped.

## Resolution — `BrandIndex` (`services/brands.py`)

The key is `brand_key(name)` (`models.py`): lower case, ё→е, whitespace and
`- _ .` removed. Cyrillic and Latin are not folded, so «Зубр» vs «Zubr» needs an
alias. Resolution order:

1. A `BrandAlias` with that key. `brand` NULL means «игнорировать» (no brand).
2. Otherwise the name key of an **active** PIM brand, if exactly one has it. When
   two active brands share a key (a PIM duplicate such as STAYER/Stayer), nothing
   matches; the queue marks the name «дубль в PIM».
3. Otherwise unresolved: the name waits in the window.

A spelling whose key is empty («-», «.») counts as no brand, not as unresolved.
Migration `0020` seeds ignore-aliases: «Без бренда», «Нет бренда», «Noname»,
«Russia», «Россия». A country «brand» would glue different makers' products by
article.

`apply_brand_resolution(qs)` runs one `UPDATE` per brand, and only on rows whose
brand differs. It uses `update()`, so `SupplierProduct.updated_at` (the time of
the supplier's data) does not move. Callers:

- the import's `_apply`, for the rows it wrote;
- `resolve_unmapped()` after a new brand is created;
- `resolve_all()` after an alias is added, changed or deleted, and at the end of
  every `sync_brands_from_pim`. An alias can pull a spelling *away* from its
  implicit brand, and a deactivated brand stops matching.

## Import traps

- **Auto-detect needs `AUTO_LINK_EXCLUDE`.** Its substring pass picks the longest
  alias, so «Артикул производителя» would go to `brand_name` ahead of `article`
  («производитель» is longer than «артикул»). Any header containing «артикул»,
  «код», «article», «sku» or «номер» is never auto-detected as the brand.
- **A brand is not a value.** `brand_name` is left out of the «row has values»
  check. A row with only a brand is dropped like a row with nothing.
- **A vanished row keeps its brand.** `brand_name` is not in
  `Setting.clearable_fields`: it is identity, not stock or price. An empty cell in
  a *mapped* brand column still writes NULL, like any other mapped field.
- **Existing settings lost the column in 0010.** `backfill_supplier_brands`
  (`functions.backfill_brands`) finds the column in each setting's latest file
  and maps only that key. `remap_links_to_columns` is not used, because it would
  drop other links whose columns vanished. The command then writes **only**
  `brand_name`/`brand` to rows matched by (article, name), honouring
  `RENAME_FROM`. `--dry-run` runs the whole thing in a rolled-back transaction.

## PIM side

- **`sync_brands_from_pim`** reads the whole `Brand` list, sorted by `id`. PIM
  paging on a field with ties drops and duplicates rows. A truncated listing
  raises instead of deactivating the brands it did not see. A brand that is
  missing from the listing, or has `isActive` false, becomes `is_active=False`;
  it is never deleted, because `PriceManagerBrand` is PROTECT.
- **`create_pim_brand`** («Создать в PIM») re-reads the list before creating:
  someone may have added the brand in PIM since the last sync. It creates with
  `upsert_async` and then **searches again** instead of trusting the result,
  since `upsertAsync` can store a row and still report it `Failed` (see
  [[product/pim-set-writes]]). Several PIM brands with the key make it refuse.
  The cached instance metadata (2026-10-06) shows `Brand.name` required and
  `code` optional and unique.
- **`merge_brands(loser, winner)`** applies to inactive brands only, from the
  window. It moves `Product.brand`, `SupplierProduct.brand`, aliases and
  `PriceManagerBrand` (dropping the loser's row where a rule already has the
  winner), turns the loser's name into an alias of the winner, then deletes the
  loser. It refuses (`BrandMergeConflict`, shown in the modal) while a Product
  of the loser has a same-number twin of the winner: moving it would create a
  second copy of a (number, brand) pair.

## The window (`brand_views.py`)

- **Mapping happens in a modal.** Its success response carries OOB fragments
  (coverage, queue count, queue) and an `HX-Trigger: brand-mapped` that closes
  the modal; a full reload would lose the scroll position in a queue of hundreds.
- **Enter must not map a brand.** The modal's form starts with a **disabled
  hidden submit**. Without it, Enter in the brand search or the name field
  triggers the first submit in the form, which is a suggestion button, and maps
  the wrong brand.
- **Suggestions** (`difflib` over brand keys) are computed only in the modal. For
  every name in the list they would cost seconds per render.
- **Coverage** is the gauge for moving on to (brand, article) identity. A ГП
  supplier row counts as branded if its `SupplierProduct.brand` is set or its
  Product has a PIM brand. `sp_mapped` counts **claims only**: named rows,
  excluding spellings that resolve to «no brand». An ignore-spelling row can now
  carry an inherited brand, and counting it would inflate «сведено» and shrink
  «игнор». `mp_with_brand` is unchanged in value, because an inherited brand
  equals its Product's brand anyway.
