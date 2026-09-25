---
title: The parse pipeline — functions.py
summary: Aggressive caching, the load_setting/get_sps contracts, get_sps refusing with a reason.
code: price_manager/supplier_product_manager/functions.py
---
# The parse pipeline — functions.py

## `functions.py` — the pipeline, and it caches aggressively

- `get_df(pk, recache=False)` (`:232`) / `get_df_sheet_names(pk)` (`:210`) read
  the spreadsheet with pandas. `get_df` caches the DataFrame under
  `_df_cache_key(setting, sf)` (`:224`): setting pk, file pk, **the instance's**
  `sheet_name` and `index_row`. Until #202 the key interpolated the class
  attribute `Setting.sheet_name` — one key for every sheet — so switching the
  sheet served the old sheet's columns until the entry expired.
- `get_sps(setting_or_pk, recache=False)` (`:410`) is the expensive one. It is
  keyed by `_get_sps_cache_key(setting, signature)` (`:405`) where the signature
  comes from `_get_setting_signature(setting)` (`:369`). **If you change what a
  `Setting` or its `Link`s mean, check that the signature covers your new
  field** — otherwise edits silently serve a stale parse. It already covers a
  `Link` being deleted (the signature hashes `setting.links`), so a data
  migration that removes `Link` rows correctly busts every affected Setting's
  sps cache — no manual cache-bump needed for that specific case.
- `auto_detect_link_keys(columns)` (`:146`) guesses column→field mapping;
  `_normalize_column_name` (`:139`) is its matcher.
- `resolve_conflicts(qs)` (`:196`), `load_setting(pk)` (`:1012`), and the
  formset builders `get_linkformset` (`:300`) / `get_dictformset` (`:284`) /
  `get_indicts` (`:327`) back the mapping UI.
- User column preferences cached per user: `save_user_sp_columns` (`:81`) /
  `load_user_sp_columns` (`:89`). `load_user_sp_columns` returns whatever was
  cached **without re-validating** against `SP_AVAILABLE_COLUMN_MAP` — the
  filtering happens downstream in `SupplierProductListTable.__init__`
  (`tables.py:159-165`), which drops unknown keys and falls back to
  `SP_DEFAULT_VISIBLE_COLUMNS` if nothing survives. So a stale cached column
  name (e.g. from before a field was removed from the table) is inert, not a
  bug — same self-healing pattern the shift-to-product brief documents for
  the old main page's column cache.

`SupplierFileStorageMissingError` (`:106`) subclasses `FileNotFoundError` — the
file row outlived its storage object.

## Two `load_setting`/`get_sps` contracts that look like bugs

Both were established deliberately and both had a stale test asserting the
opposite for months, so read them before "fixing" either.

**A re-upload busts the sps cache, by design.** `_get_setting_signature`
(`:369`) hashes the newest `SupplierFile`'s **id, name and size** alongside the
setting and its links. So replacing the file — even with an identical-looking
one — changes the signature and forces a fresh parse. Serving the cached rows
after an upload would be the bug; the cache exists to skip repeated reads of an
*unchanged* file, not to pin a snapshot.

**Rows missing from the new file are nulled, not zeroed — absence lives on the
raw layer and is resolved on the derived one.** `_apply` (`:1034`, called from
`load_setting`, `:1012`) runs `missing_sps.update(stock=None)` (`:1096`) and,
per mapped price column, `missing_sps.update(**{column: None})` (`:1101`). A
vanished row means the supplier gave no figure, so `SupplierProduct` records
that absence; it never invents a synced `0`. Every consumer resolves it for
itself: [[main_product_manager]]'s `update_stocks` coalesces a NULL supplier
stock to `0` (unknown stock is not sellable) and [[product_price_manager]]
treats a NULL (or 0) price as "no price": its rules skip the product and
`clear_unsourced_prices()` sets the prices computed from it to NULL. Note the
carve-out: only columns the setting still **maps** get cleared, so deleting a
`Link` freezes that field at its last imported value.

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
  a `unique=True` FK (still true today — `models.py:16-30`), so one
  `MainProduct` can hold at most one `SupplierProduct` and the duplicate-row
  choice that test covered can no longer arise. #137 restored the NULL,
  matching the two-layer rule the `update_stocks` docstring
  (`main_product_manager/utils.py:457`) already states in code.

Verify a cited test still exists before you trust it — `git log --all -S`
distinguishes "never existed" from "deleted last hour", and here the two led
to different conclusions.

**`auto_detect_link_keys` (`:146`) matches in two passes**, and only the second
is order-sensitive: exact normalized-name match first across all columns, then a
substring sweep for whatever is left, with each key claimable once. The
substring pass picks the **longest** matching alias rather than the
first-declared key — required once bare `"цена"` became a `supplier_price`
alias, since it is a substring of `"ценасоскидкой"` and declaration order alone
would let it steal a "Цена со скидкой, руб" column from `discount_price`.

**Its alias table is independent of `LINKS` — deleting a `LINKS` entry does
not stop it being auto-detected.** `AUTO_LINK_ALIASES` (`:94-103`) seeds the
alias map on its own; the loop over `LINKS.items()` (`:160`) only *adds*
each key's verbose name/own key as extra aliases, it never gates which keys
exist. So removing a key from `LINKS` (e.g. `'manufacturer'`/`'category'` in
Phase 2b) without also removing it from `AUTO_LINK_ALIASES` would leave it
live, `auto_detect_link_keys` would keep returning it for a matching column,
and `SettingUpdate.form_valid` (`views.py:456-462`) would
`Link.objects.get_or_create(setting=setting, key=<removed key>)` again the
next time that Setting's mapping screen is saved with no explicit
selection — silently recreating orphan `Link` rows a cleanup migration just
deleted. **Removing a key from `LINKS` alone is not enough; its
`AUTO_LINK_ALIASES` entry has to go too.** Phase 2b-2 did both for
`category`/`manufacturer`, and current `AUTO_LINK_ALIASES`
(`functions.py:94-103`) has no entries for either — confirmed clean.

## `get_sps` never returns nothing — it refuses with a reason

Since #202 `get_sps` returns a non-empty list or raises `SupplierImportError`
(`functions.py:110`) whose message is a Russian, user-facing reason: no file,
empty sheet, no article column (listing the columns the file does have), no
name column while `create_new`, no values in any mapped column, or no row
matching the supplier's existing products. `_empty_result_reason` (`:126`)
picks among the last three by counting rows after each filter stage.

**Do not reintroduce a `None`/`[]` return "for convenience".** An empty payload
is the one input that turns `load_setting` destructive: every existing row of
the setting (see [[supplier_product_manager/matching]]) lands in `missing_sps`
and has its stock and mapped prices set to NULL. Before #202 that path was
blocked only by accident — `[]` became a column-less DataFrame and
`df.dropna(subset=['name'])` raised `KeyError ['name']`, which users saw as an
unexplained failed import. Removing that crash without the explicit refusal
would have wiped a supplier on any file that matched nothing (typically
`create_new=False` plus a renamed article column or whitespace drift in names).

Consumers rely on the exception:

- `_import_setting` (`tasks.py:206`, called by `process_supplier_file_import`,
  `tasks.py:138`) catches `SupplierImportError` together with
  `SupplierFileStorageMissingError` as **expected refusals** (`tasks.py:292`):
  notification «Импорт … не выполнен, данные не изменены. Причина: …», the same
  line in `SupplierFile.logs`, status `STATUS_ERROR`, and **no re-raise**. Any
  other exception is still re-raised (`tasks.py:317` onward) — and there the
  "data unchanged" claim would not hold, since `load_setting` is not atomic
  with respect to the run/notification writes (only its own DB writes are
  atomic, per [[supplier_product_manager/import-run-and-guard]]).
- The mapping screen's preview, `SettingSPSTableView` (`views.py:326`), already
  rendered `str(ex)` for any exception, so it shows the same reason with no
  change of its own.

**A mapped column missing from the file** is handled per case in `get_sps`:
the article column raises; a column whose `Link` has an `initial` falls back to
that constant (it used to raise a bare `KeyError` from `fillna`); any other
missing column is still silently skipped. Making the last case an error was
considered and left out on purpose — it would start failing imports that
succeed today. That "missing column" case is now also surfaced separately as
`stats['missing_columns']` and used by the import guard (see
[[supplier_product_manager/import-run-and-guard]]) — the guard can hold an
import even though `get_sps` itself does not error for it.
