# supplier_product_manager

Biggest app by line count (3187 LOC). `SupplierProduct` is the supplier's raw
price row; the rest of the app is the **Excel import pipeline** that produces
those rows. Most of the complexity is in the pipeline, not the model.

## The import config is a four-model chain

`Setting` → `Link` → `DictItem`, plus `SupplierFile` as the upload queue.

- **`Setting`** (`models.py:113`) — one named import profile per supplier.
  `sheet_name`, `index_row` (which row holds the headers), `create_new`
  (create `SupplierProduct`s that don't exist yet), `ignore_name`.
  Unique on `(name, supplier)`.
- **`Link`** (`models.py:143`) — maps one spreadsheet column (`value`) to one
  model field (`key`, chosen from the `LINKS` dict at `models.py:100`).
  `initial` holds the original column caption. Unique on `(setting, key)`.
  `key` is a plain `CharField(choices=LINKS)` — Django only validates
  `choices` on `full_clean()`, never on `save()`, so a `Link` row with a
  `key` no longer present in `LINKS` is not rejected by the model layer.
  That is why `load_setting` filters its links to `LINKS` keys itself: every
  key becomes a `SupplierProduct(**data)` kwarg, and a key naming a removed
  field would fail the whole import.
- **`DictItem`** (`models.py:156`) — per-link value translation, literally
  `key`/`value` with Russian verbose names "Если" / "То" (if/then). This is how
  a supplier's "в наличии" becomes a stock number.
- **`SupplierFile`** (`models.py:171`) — the uploaded file, its `setting`,
  an integer `status`, and a `logs` text field appended to by
  `_append_supplier_file_log` (`tasks.py:21`).

**`Setting.is_bound()`** (`models.py:133`) is the readiness check — and it has a
side effect: it rewrites `Link`s whose `value` is `''` to `None` before
validating. It returns False unless an `article` link exists, and (when
`create_new`) a `name` link too. Calling it is not free and not read-only.

## Price/number field constants (`models.py:12`)

```
SP_TABLE_FIELDS = ['article','name','manufacturer','supplier_price','rrp','discount']
SP_PRICES  = ['supplier_price', 'rrp', 'discount_price']
SP_NUMBERS = SP_PRICES + ['stock']
```
`SP_PRICES` is imported by [[product_price_manager]] as the source-price
vocabulary. Adding a price field here means checking that app too.

## `functions.py` — the pipeline, and it caches aggressively

- `get_df(pk, recache=False)` (`:170`) / `get_df_sheet_names(pk)` (`:156`) read
  the spreadsheet with pandas.
- `get_sps(setting_or_pk, recache=False)` (`:337`) is the expensive one. It is
  keyed by `_get_sps_cache_key(setting, signature)` (`:332`) where the signature
  comes from `_get_setting_signature(setting)` (`:296`). **If you change what a
  `Setting` or its `Link`s mean, check that the signature covers your new
  field** — otherwise edits silently serve a stale parse. It already covers a
  `Link` being deleted (the signature hashes `setting.links`), so a data
  migration that removes `Link` rows correctly busts every affected Setting's
  sps cache — no manual cache-bump needed for that specific case.
- `auto_detect_link_keys(columns)` (`:92`) guesses column→field mapping;
  `_normalize_column_name` (`:85`) is its matcher.
- `resolve_conflicts(qs)` (`:142`), `load_setting(pk)` (`:427`), and the
  formset builders `get_linkformset` (`:227`) / `get_dictformset` (`:211`) /
  `get_indicts` (`:254`) back the mapping UI.
- User column preferences cached per user: `save_user_sp_columns` (`:54`) /
  `load_user_sp_columns` (`:62`). `load_user_sp_columns` returns whatever was
  cached **without re-validating** against `SP_AVAILABLE_COLUMN_MAP` — the
  filtering happens downstream in `SupplierProductListTable.__init__`
  (`tables.py:108`), which drops unknown keys and falls back to
  `SP_DEFAULT_VISIBLE_COLUMNS` if nothing survives. So a stale cached column
  name (e.g. from before a field was removed from the table) is inert, not a
  bug — same self-healing pattern the shift-to-product brief documents for
  the old main page's column cache.

`SupplierFileStorageMissingError` (`:81`) subclasses `FileNotFoundError` — the
file row outlived its storage object.

## Two `load_setting`/`get_sps` contracts that look like bugs

Both were established deliberately and both had a stale test asserting the
opposite for months, so read them before "fixing" either.

**A re-upload busts the sps cache, by design.** `_get_setting_signature`
(`:296`) hashes the newest `SupplierFile`'s **id, name and size** alongside the
setting and its links. So replacing the file — even with an identical-looking
one — changes the signature and forces a fresh parse. Serving the cached rows
after an upload would be the bug; the cache exists to skip repeated reads of an
*unchanged* file, not to pin a snapshot.

**Rows missing from the new file are nulled, not zeroed — absence lives on the
raw layer and is resolved on the derived one.** `load_setting` (`:496`–`:503`)
runs `missing_sps.update(stock=None)` and, per mapped price column,
`missing_sps.update(**{column: None})`. A vanished row means the supplier gave
no figure, so `SupplierProduct` records that absence; it never invents a synced
`0`. Every consumer resolves it for itself: [[main_product_manager]]'s
`update_stocks` coalesces a NULL supplier stock to `0` (unknown stock is not
sellable) and [[product_price_manager]]'s `PriceTag.get_sprice`
(`models.py:412`) reads a NULL price as `Decimal('0')`. Note the carve-out:
only columns the setting still **maps** get cleared, so deleting a `Link`
freezes that field at its last imported value.

The history here has flipped twice and both flips left a trap, so do not
re-derive it from either artifact:

- `8774795` ("Handle NULL/0 sync…") switched the raw layer from `None` to `0`
  **and** in the same commit made the derived layer NULL-safe
  (`Max(Coalesce(source, 0))` in `PriceManager`, list normalisation in
  `get_sprice`). The second half made the first half redundant.
- `11da6e4` then kept the `0` and justified it with
  [[product_price_manager]]'s
  `test_pricemanager_with_duplicate_supplier_products_prefers_positive_value`.
  **That test had been deleted 50 minutes earlier**, by `c819a63` — an
  ancestor of `11da6e4` itself. And it was deleted for a reason that retires
  the argument outright: migration `0009` made `SupplierProduct.main_product`
  a `unique=True` FK, so one `MainProduct` can hold at most one
  `SupplierProduct` and the duplicate-row choice that test covered can no
  longer arise. #137 restored the NULL, matching the two-layer rule the
  `update_stocks` docstring (`main_product_manager/utils.py:386`) already
  states in code.

Verify a cited test still exists before you trust it — `git log --all -S`
distinguishes "never existed" from "deleted last hour", and here the two led
to different conclusions.

**`auto_detect_link_keys` (`:92`) matches in two passes**, and only the second
is order-sensitive: exact normalized-name match first across all columns, then a
substring sweep for whatever is left, with each key claimable once. The
substring pass picks the **longest** matching alias rather than the
first-declared key — required once bare `"цена"` became a `supplier_price`
alias, since it is a substring of `"ценасоскидкой"` and declaration order alone
would let it steal a "Цена со скидкой, руб" column from `discount_price`.

**Its alias table is independent of `LINKS` — deleting a `LINKS` entry does
not stop it being auto-detected.** `AUTO_LINK_ALIASES` (`:67-78`) seeds the
alias map on its own; the loop over `LINKS.items()` (`:106-110`) only *adds*
each key's verbose name/own key as extra aliases, it never gates which keys
exist. So removing `'manufacturer'`/`'category'` from `LINKS` (D11 in the
shift-to-product brief) leaves `AUTO_LINK_ALIASES["manufacturer"] =
("manufacturer", "brand", "бренд", "производитель")` live, `auto_detect_link_keys`
keeps returning `'manufacturer'` for such a column, and `SettingUpdate.form_valid`
(`views.py:316-333`) will `Link.objects.get_or_create(setting=setting,
key='manufacturer')` again the next time that Setting's mapping screen is
saved with no explicit selection — silently recreating the exact orphan `Link`
rows a cleanup migration just deleted. **Removing a key from `LINKS` alone is
not enough; its `AUTO_LINK_ALIASES` entry has to go too.** Phase 2b-2 did both
for `category`/`manufacturer`; `test_brand_and_category_columns_are_left_unmapped`
pins it.

## Tasks — the known convention exception

All four `@shared_task`s in `tasks.py` do their work **inline**, not through
`execute_locked_task`: `process_supplier_file_import` (`:31`),
`process_setting_upload` (`:135`), `cleanup_supplier_files_task` (`:140`),
`copy_supplier_products_to_main_task` (`:194`). This is pre-existing and
documented as a known exception in the convention reviewer — do not report it
as a new finding, but **new** tasks here should route through it.

`copy_supplier_products_to_main_task` is the bridge into
[[main_product_manager]]; it records a `CopySupplierProductsToMainRun` row
(`models.py:208`) with `processed_count` / `created_count` /
`updated_links_count`, restores a saved filter via `_restore_querydict`
(`tasks.py:171`) and batches with `_chunked` (`:183`). Since Phase 2b-2 it copies nothing but the row itself: `MainProduct` lost
`manufacturer`, `description` and `categories`, and `SupplierProduct` lost
`category` and `manufacturer`. What it still does besides creating rows is
**link them to `product.Product` — explicitly**, via
[[main_product_manager]]'s `link_to_local_products(ids)`: one lookup and one
bulk update per chunk, existing Products only (`number=sku`), never creates one.
Before 2b-2 the link was a side effect of rebuilding `MainProduct.search_vector`;
dropping the vector without this step would have left every imported row with
`product IS NULL`, invisible on `/products/` until the nightly
`reindex_pim_ids`, with no error. For a brand-new row the matching `Product`
usually doesn't exist yet (its `sku` was just computed), so the step mostly
helps rows whose `Product` appeared since; creating Products stays reindex's
job (`link_unlinked_main_products`, which is unscoped and table-wide).

## Removing a mapped field — the checklist 2b-2 needed

When a `SupplierProduct` field goes away, these all name it as a literal and
must move in the same change:

- `LINKS` **and** `AUTO_LINK_ALIASES` (see above), plus a data migration
  deleting the `Link` rows that map it — report the count, don't do it silently.
- `SP_TABLE_FIELDS`, `SupplierProductListTable.Meta.fields`,
  `SP_AVAILABLE_COLUMN_GROUPS`/`SP_DEFAULT_VISIBLE_COLUMNS` (stale cached
  column choices are inert — `tables.py` drops unknown keys at render).
- `SupplierProductFilter` fields, facet setup and `_apply_current_filters`.
- `SupplierProductResource` fields.
- **`admin.py` `list_filter`** — a stale entry fails Django's admin check
  **E116** at `check`/`migrate`/test startup: the whole suite, not one page.
  `list_display` (derived from `_meta.fields`) self-heals.
- `SPS_JSON_FIELDS` (feeds the file-preview headers) — and bump
  `SPS_JSON_SCHEMA_VERSION`, so a parse cached under the old shape is not
  served for up to `SPS_CACHE_TTL_SECONDS`.

## Imports up, not down

`models.py` imports `MainProduct` and all of `supplier_manager`. Nothing in
`main_product_manager` imports back — keep that direction.

`admin.py` transitively imports `main_product_manager.pim_client`, which
instantiates `SiteAPI` at module import. Unset `PIM_TOKEN`/`PIM_HOST` therefore
break **app boot from here**, not just PIM features.
