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

- `get_df(pk, recache=False)` (`:164`) / `get_df_sheet_names(pk)` (`:150`) read
  the spreadsheet with pandas.
- `get_sps(setting_or_pk, recache=False)` (`:331`) is the expensive one. It is
  keyed by `_get_sps_cache_key(setting, signature)` (`:326`) where the signature
  comes from `_get_setting_signature(setting)` (`:290`). **If you change what a
  `Setting` or its `Link`s mean, check that the signature covers your new
  field** — otherwise edits silently serve a stale parse.
- `auto_detect_link_keys(columns)` (`:92`) guesses column→field mapping;
  `_normalize_column_name` (`:85`) is its matcher.
- `resolve_conflicts(qs)` (`:136`), `load_setting(pk)` (`:421`), and the
  formset builders `get_linkformset` (`:221`) / `get_dictformset` (`:205`) /
  `get_indicts` (`:248`) back the mapping UI.
- User column preferences cached per user: `save_user_sp_columns` (`:54`) /
  `load_user_sp_columns` (`:62`).

`SupplierFileStorageMissingError` (`:81`) subclasses `FileNotFoundError` — the
file row outlived its storage object.

## Two `load_setting`/`get_sps` contracts that look like bugs

Both were established deliberately and both had a stale test asserting the
opposite for months, so read them before "fixing" either.

**A re-upload busts the sps cache, by design.** `_get_setting_signature`
(`:290`) hashes the newest `SupplierFile`'s **id, name and size** alongside the
setting and its links. So replacing the file — even with an identical-looking
one — changes the signature and forces a fresh parse. Serving the cached rows
after an upload would be the bug; the cache exists to skip repeated reads of an
*unchanged* file, not to pin a snapshot.

**Rows missing from the new file are zeroed, not nulled.** `load_setting`
(`:484`–`:491`) runs `missing_sps.update(stock=0)` and, per mapped price
column, `missing_sps.update(**{column: 0})`. It was `None` until commit
`8774795`. The 0 is load-bearing downstream — [[product_price_manager]]'s
`test_pricemanager_with_duplicate_supplier_products_prefers_positive_value`
encodes the rule that a zero price loses to a positive one, which only has
meaning because absent rows arrive as 0. Note the carve-out the test exercises:
only columns the setting still **maps** get zeroed, so deleting a `Link` freezes
that field at its last imported value rather than clearing it.

**`auto_detect_link_keys` (`:92`) matches in two passes**, and only the second
is order-sensitive: exact normalized-name match first across all columns, then a
substring sweep for whatever is left, with each key claimable once. The
substring pass picks the **longest** matching alias rather than the
first-declared key — required once bare `"цена"` became a `supplier_price`
alias, since it is a substring of `"ценасоскидкой"` and declaration order alone
would let it steal a "Цена со скидкой, руб" column from `discount_price`.

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
(`tasks.py:171`) and batches with `_chunked` (`:183`).

## Imports up, not down

`models.py` imports `MainProduct` and all of `supplier_manager`. Nothing in
`main_product_manager` imports back — keep that direction.

`admin.py` transitively imports `main_product_manager.pim_client`, which
instantiates `SiteAPI` at module import. Unset `PIM_TOKEN`/`PIM_HOST` therefore
break **app boot from here**, not just PIM features.
