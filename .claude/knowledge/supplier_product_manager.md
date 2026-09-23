# supplier_product_manager

`SupplierProduct` is the supplier's raw price row; the rest of the app is the
**Excel import pipeline** that produces those rows. Most of the complexity is
in the pipeline, not the model.

## The import config is a four-model chain

`Setting` → `Link` → `DictItem`, plus `SupplierFile` as the upload queue.

- **`Setting`** (`models.py:99`) — one named import profile per supplier.
  `sheet_name`, `index_row` (which row holds the headers), `create_new`
  (create `SupplierProduct`s that don't exist yet), `ignore_name`.
  Unique on `(name, supplier)`.
- **`Link`** (`models.py:129`) — maps one spreadsheet column (`value`) to one
  model field (`key`, chosen from the `LINKS` dict at `models.py:88`).
  `initial` holds the original column caption. Unique on `(setting, key)`.
  `key` is a plain `CharField(choices=LINKS)` — Django only validates
  `choices` on `full_clean()`, never on `save()`, so a `Link` row with a
  `key` no longer present in `LINKS` is not rejected by the model layer.
  That is why `load_setting` filters its links to `LINKS` keys itself: every
  key becomes a `SupplierProduct(**data)` kwarg, and a key naming a removed
  field would fail the whole import.
- **`DictItem`** (`models.py:142`) — per-link value translation, literally
  `key`/`value` with Russian verbose names "Если" / "То" (if/then). This is how
  a supplier's "в наличии" becomes a stock number.
- **`SupplierFile`** (`models.py:157`) — the uploaded file, its `setting`,
  an integer `status`, and a `logs` text field appended to by
  `_append_supplier_file_log` (`tasks.py:21`).

**`Setting.is_bound()`** (`models.py:119`) is the readiness check — and it has a
side effect: it rewrites `Link`s whose `value` is `''` to `None` before
validating. It returns False unless an `article` link exists, and (when
`create_new`) a `name` link too. Calling it is not free and not read-only.

## Price/number field constants (`models.py:12-14`)

```
SP_TABLE_FIELDS = ['article', 'name', 'supplier_price', 'rrp', 'discount']
SP_PRICES  = ['supplier_price', 'rrp', 'discount_price']
SP_NUMBERS = ['supplier_price', 'rrp', 'stock', 'discount_price']
```
`manufacturer` used to be in `SP_TABLE_FIELDS`; it was dropped with the rest of
the catalog fields in Phase 2b-2 (see checklist below) — don't re-add it from
memory. `SP_PRICES` is imported by [[product_price_manager]] as the
source-price vocabulary. Adding a price field here means checking that app too.

## `functions.py` — the pipeline, and it caches aggressively

- `get_df(pk, recache=False)` (`:198`) / `get_df_sheet_names(pk)` (`:177`) read
  the spreadsheet with pandas. `get_df` caches the DataFrame under
  `_df_cache_key(setting, sf)` (`:191`): setting pk, file pk, **the instance's**
  `sheet_name` and `index_row`. Until #202 the key interpolated the class
  attribute `Setting.sheet_name` — one key for every sheet — so switching the
  sheet served the old sheet's columns until the entry expired.
- `get_sps(setting_or_pk, recache=False)` (`:365`) is the expensive one. It is
  keyed by `_get_sps_cache_key(setting, signature)` (`:360`) where the signature
  comes from `_get_setting_signature(setting)` (`:324`). **If you change what a
  `Setting` or its `Link`s mean, check that the signature covers your new
  field** — otherwise edits silently serve a stale parse. It already covers a
  `Link` being deleted (the signature hashes `setting.links`), so a data
  migration that removes `Link` rows correctly busts every affected Setting's
  sps cache — no manual cache-bump needed for that specific case.
- `auto_detect_link_keys(columns)` (`:113`) guesses column→field mapping;
  `_normalize_column_name` (`:106`) is its matcher.
- `resolve_conflicts(qs)` (`:163`), `load_setting(pk)` (`:482`), and the
  formset builders `get_linkformset` (`:255`) / `get_dictformset` (`:239`) /
  `get_indicts` (`:282`) back the mapping UI.
- User column preferences cached per user: `save_user_sp_columns` (`:53`) /
  `load_user_sp_columns` (`:61`). `load_user_sp_columns` returns whatever was
  cached **without re-validating** against `SP_AVAILABLE_COLUMN_MAP` — the
  filtering happens downstream in `SupplierProductListTable.__init__`
  (`tables.py:101-107`), which drops unknown keys and falls back to
  `SP_DEFAULT_VISIBLE_COLUMNS` if nothing survives. So a stale cached column
  name (e.g. from before a field was removed from the table) is inert, not a
  bug — same self-healing pattern the shift-to-product brief documents for
  the old main page's column cache.

`SupplierFileStorageMissingError` (`:78`) subclasses `FileNotFoundError` — the
file row outlived its storage object.

## Two `load_setting`/`get_sps` contracts that look like bugs

Both were established deliberately and both had a stale test asserting the
opposite for months, so read them before "fixing" either.

**A re-upload busts the sps cache, by design.** `_get_setting_signature`
(`:324`) hashes the newest `SupplierFile`'s **id, name and size** alongside the
setting and its links. So replacing the file — even with an identical-looking
one — changes the signature and forces a fresh parse. Serving the cached rows
after an upload would be the bug; the cache exists to skip repeated reads of an
*unchanged* file, not to pin a snapshot.

**Rows missing from the new file are nulled, not zeroed — absence lives on the
raw layer and is resolved on the derived one.** `load_setting` (`:536`–`:543`)
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
  a `unique=True` FK (still true today — `models.py:24-30`), so one
  `MainProduct` can hold at most one `SupplierProduct` and the duplicate-row
  choice that test covered can no longer arise. #137 restored the NULL,
  matching the two-layer rule the `update_stocks` docstring
  (`main_product_manager/utils.py:457`) already states in code.

Verify a cited test still exists before you trust it — `git log --all -S`
distinguishes "never existed" from "deleted last hour", and here the two led
to different conclusions.

**`auto_detect_link_keys` (`:113`) matches in two passes**, and only the second
is order-sensitive: exact normalized-name match first across all columns, then a
substring sweep for whatever is left, with each key claimable once. The
substring pass picks the **longest** matching alias rather than the
first-declared key — required once bare `"цена"` became a `supplier_price`
alias, since it is a substring of `"ценасоскидкой"` and declaration order alone
would let it steal a "Цена со скидкой, руб" column from `discount_price`.

**Its alias table is independent of `LINKS` — deleting a `LINKS` entry does
not stop it being auto-detected.** `AUTO_LINK_ALIASES` (`:66-75`) seeds the
alias map on its own; the loop over `LINKS.items()` (`:127-131`) only *adds*
each key's verbose name/own key as extra aliases, it never gates which keys
exist. So removing a key from `LINKS` (e.g. `'manufacturer'`/`'category'` in
Phase 2b) without also removing it from `AUTO_LINK_ALIASES` would leave it
live, `auto_detect_link_keys` would keep returning it for a matching column,
and `SettingUpdate.form_valid` (`views.py:338-356`) would
`Link.objects.get_or_create(setting=setting, key=<removed key>)` again the
next time that Setting's mapping screen is saved with no explicit
selection — silently recreating orphan `Link` rows a cleanup migration just
deleted. **Removing a key from `LINKS` alone is not enough; its
`AUTO_LINK_ALIASES` entry has to go too.** Phase 2b-2 did both for
`category`/`manufacturer`, and current `AUTO_LINK_ALIASES`
(`functions.py:66-75`) has no entries for either — confirmed clean.

## `get_sps` never returns nothing — it refuses with a reason

Since #202 `get_sps` returns a non-empty list or raises `SupplierImportError`
(`functions.py:82`) whose message is a Russian, user-facing reason: no file,
empty sheet, no article column (listing the columns the file does have), no
name column while `create_new`, no values in any mapped column, or no row
matching the supplier's existing products. `_empty_result_reason` (`:93`)
picks among the last three by counting rows after each filter stage.

**Do not reintroduce a `None`/`[]` return "for convenience".** An empty payload
is the one input that turns `load_setting` destructive: every existing row of
the supplier lands in `missing_sps` (`:528`) and has its stock and mapped prices
set to NULL. Before #202 that path was blocked only by accident — `[]` became a
column-less DataFrame and `df.dropna(subset=['name'])` raised `KeyError
['name']`, which users saw as an unexplained failed import. Removing that crash
without the explicit refusal would have wiped a supplier on any file that
matched nothing (typically `create_new=False` plus a renamed article column or
whitespace drift in names).

Consumers rely on the exception:

- `process_supplier_file_import` (`tasks.py:81`) catches `SupplierImportError`
  together with `SupplierFileStorageMissingError` as **expected refusals**:
  notification «Импорт … не выполнен, данные не изменены. Причина: …», the same
  line in `SupplierFile.logs`, status `STATUS_ERROR`, and **no re-raise**. Any
  other exception is still re-raised (`:107`) — and there the "data unchanged"
  claim would not hold, since `load_setting` is not atomic.
- The mapping screen's preview, `SettingSPSTableView` (`views.py:229`), already
  rendered `str(ex)` for any exception, so it shows the same reason with no
  change of its own.

**A mapped column missing from the file** is handled per case in `get_sps`:
the article column raises; a column whose `Link` has an `initial` falls back to
that constant (it used to raise a bare `KeyError` from `fillna`); any other
missing column is still silently skipped. Making the last case an error was
considered and left out on purpose — it would start failing imports that
succeed today.

## Import history — `ImportRun` and the parse counters

Every run of `process_supplier_file_import` leaves one `ImportRun`
(`models.py`) — `applied`, `refused` (a `SupplierImportError` or missing
storage file, `message` = the user-facing reason) or `failed` (anything else,
re-raised). It is the per-setting coverage history the import guard compares a
new file against, so **do not add an import path that bypasses the task**
without recording a run.

- The counters come from `get_sps_result` (`functions.py`), which returns
  `(payload, stats)`; `get_sps` is its payload-only wrapper. Stage counters are
  listed in `SPS_STAT_FIELDS`. Payload and stats are cached **together** under
  schema version `1.2` — a bare-list entry from `1.1` would break the unpack, so
  changing the cached shape again means bumping `SPS_JSON_SCHEMA_VERSION`.
- **Price and stock coverage are separate on purpose** (`covered_price`,
  `covered_stock`, `_coverage`): a stock column can stop parsing, or lose its
  `Link`, while prices keep loading, and the total row count hides that. An
  unmapped stock yields `covered_stock = 0`, the same as a column where no
  number parsed. Production has had exactly this — suppliers with prices on
  nearly every row and stock NULL on nearly all of them.
- A refusal carries the counters gathered so far on `exc.stats`, so a refused
  run shows where the rows were lost. `created`/`updated`/`missing` exist only
  for applied runs (`load_setting` returns `ImportOutcome(sps, stats)`).
- `supplier_file` is `SET_NULL` with `file_name` copied: the cleanup task deletes
  files, the history must outlive them.

## The import guard — confirmation instead of a silent bad import

`process_supplier_file_import` parses first (`get_sps_result` + `apply_counts`),
then asks `guard.evaluate` whether to apply. It holds the import (status
`pending`, `SupplierFile.STATUS_NEEDS_CONFIRMATION`, a `warning` notification
whose link opens the dialog) when:

- the setting has fewer than `SUPPLIER_IMPORT_GUARD_MIN_HISTORY` (3) applied
  runs — **every** import asks until history exists; there is deliberately no
  history-free heuristic and no seeding from old notifications;
- `covered_price` or `covered_stock` is below `SUPPLIER_IMPORT_GUARD_RATIO`
  (0.7) × the **median** of the last `SUPPLIER_IMPORT_GUARD_WINDOW` (5) applied
  runs. Median, not mean: one force-applied outlier must not drag the
  baseline. A metric whose median is 0 (the setting never delivered it) is
  not checked. Thresholds live in `settings/project.py`.

Confirmed runs are `applied` runs, so they feed the history: a genuine shrink
stops asking after a few confirmations.

Confirmation mechanics — each piece closes a specific race:

- `import_run_apply` claims the run with a conditional
  `UPDATE … WHERE status='pending'` → `running` and dispatches through
  `dispatch_after_commit`; a double click finds nothing to claim.
- The confirmed task re-applies **without** a second check, but only if the
  newest file and `_get_setting_signature` still match `ImportRun.signature`;
  otherwise the run becomes `superseded`. A confirmation never applies a file
  or mapping the user did not see.
- A new import of the setting, or a new upload, marks a pending run
  `superseded`. Cleanup skips files in `STATUS_NEEDS_CONFIRMATION`.
- `load_setting` writes inside `transaction.atomic()` (`_apply`): upsert,
  clearing of missing rows and `supplier.save()` land together or not at all.

UI: `SettingListTable.last_import` (annotated by `SettingList.get_queryset`,
one subquery, no N+1) shows the last run; a pending one is a button opening
`import_confirm_modal.html` in its own compact `#import-confirm-modal` on the
supplier page (not the shared `modal-xl` container). `SupplierDetail` opens it
on load for `?import_run=<pk>` only while that run is still pending, so the
`HttpResponseClientRefresh` after apply/cancel does not reopen it.

## Upload and cleanup — the file a setting depends on

- **`UploadSupplierFile.form_valid`** (`views.py:145`) reads the workbook's
  sheet names **before** creating anything. It used to create the `Setting`
  first and read the file inside a `while not created` loop with `except
  BaseException`, so a corrupt or password-protected file was taken for a name
  clash and the loop kept creating `name(1)`, `name(2)`, … until gunicorn killed
  the worker. Name suffixing is now bounded by `MAX_SETTING_NAME_ATTEMPTS`
  (`views.py:51`) and catches only `IntegrityError` inside a savepoint. Empty
  `Setting`s with a `(N)` suffix, no file and no links are likely leftovers of
  the old loop.
- **`cleanup_supplier_files_task`** (`tasks.py:131`) never deletes a setting's
  newest file: `keep_last` is clamped to at least 1 and
  `SUPPLIER_FILES_KEEP_LAST` defaults to 1 (`settings/celery.py`). It used to
  default to 0, which on a 30-minute beat deleted every file — including the
  one being mapped or waiting in the import queue. Files in
  `STATUS_QUEUED`/`STATUS_RUNNING` are skipped too. Note the upload view itself
  already deletes all previous files of the setting, so in practice there is
  one file per setting and the cleanup mostly handles orphans.

## Known open problems in the import (not fixed yet)

Recorded so the next person does not rediscover them; each needs a design
decision, not a quick patch.

- **`missing_sps` is supplier-wide, not setting-wide** (`functions.py:528`).
  Two settings of one supplier that both map `stock` or a price (e.g. two
  warehouses, or stock and prices in separate files) null each other's rows on
  every import. Production has such a supplier. A `SupplierProduct` does not
  record which setting last loaded it, so there is nothing to scope by yet.
- **Identity is `(supplier, article, name)`** (`models.py:78-83`). A supplier
  fixing a typo in a name creates a new row and nulls the old one, which loses
  its `main_product` link. Many articles in production already carry more than
  one name per supplier.
- **Stored articles and names carry leading/trailing whitespace** — common in
  production. `get_df` collapses runs of whitespace but does not strip. Adding a
  `strip()` to the parser alone would re-key every such row on the next import
  (new row created, old one nulled); it needs a data migration that trims
  stored values and resolves the rows that collide after trimming, some of
  them linked to a `MainProduct`.
- **Numbers**: only `','→'.'` before `pd.to_numeric(errors='coerce')`
  (`get_sps`), so `1 234,50`, `1,234.50`, currency signs, `>10`, `10+` become
  NaN; a row whose every mapped value is NaN is dropped and then nulled as
  "missing". A non-integer `stock` value fails the whole import.
- **`DictItem` replacement is substring-based** (`str.replace`), so «в
  наличии → 10» also rewrites «нет в наличии».
- **NULL source price is not "no price" downstream**: [[product_price_manager]]'s
  `get_fitting_mps` coalesces it to 0, so a rule without `price_from`/`price_to`
  sets the product's price to the rule's `increase`.
- **`resolve_conflicts` runs inside `get_sps`**, so even the read-only preview
  may create duplicate `SupplierProduct`s for names containing non-space
  whitespace; and the name lookups in `get_sps` are one query per file row.

## Tasks — the known convention exception

All four `@shared_task`s in `tasks.py` do their work **inline**, not through
`execute_locked_task`: `process_supplier_file_import` (`:32`),
`process_setting_upload` (`:126`), `cleanup_supplier_files_task` (`:131`),
`copy_supplier_products_to_main_task` (`:191`). This is pre-existing and
documented as a known exception in the convention reviewer — do not report it
as a new finding, but **new** tasks here should route through it.

`copy_supplier_products_to_main_task` is the bridge into
[[main_product_manager]]; it records a `CopySupplierProductsToMainRun` row
(`models.py:194`) with `processed_count` / `created_count` /
`updated_links_count`, restores a saved filter via `_restore_querydict`
(`tasks.py:167`) and batches with `_chunked` (`:179`). Since Phase 2b-2 it
copies nothing but the row itself: `MainProduct` lost `manufacturer`,
`description` and `categories`, and `SupplierProduct` lost `category` and
`manufacturer`. What it still does besides creating rows is **link them to
`product.Product` — explicitly**, via [[main_product_manager]]'s
`link_to_local_products(ids)`: one lookup and one bulk update per chunk,
existing Products only (`number=sku`), never creates one. Before 2b-2 the link
was a side effect of rebuilding `MainProduct.search_vector`; dropping the
vector without this step would have left every imported row with `product IS
NULL`, invisible on `/products/` until the nightly `reindex_pim_ids`, with no
error. For a brand-new row the matching `Product` usually doesn't exist yet
(its `sku` was just computed), so the step mostly helps rows whose `Product`
appeared since; creating Products stays reindex's job
(`link_unlinked_main_products`, which is unscoped and table-wide).

## Removing a mapped field — the checklist 2b-2 needed

When a `SupplierProduct` field goes away, these all name it as a literal and
must move in the same change:

- `LINKS` **and** `AUTO_LINK_ALIASES` (see above), plus a data migration
  deleting the `Link` rows that map it — report the count, don't do it silently.
- `SP_TABLE_FIELDS`, `SupplierProductListTable.Meta.fields`,
  `SP_AVAILABLE_COLUMN_GROUPS`/`SP_DEFAULT_VISIBLE_COLUMNS` (stale cached
  column choices are inert — `tables.py` drops unknown keys at render).
- `SupplierProductFilter` fields, facet setup and `_apply_current_filters`
  (`filters.py:152`).
- `SupplierProductResource` fields (`resources.py`).
- **`admin.py` `list_filter`** — a stale entry fails Django's admin check
  **E116** at `check`/`migrate`/test startup: the whole suite, not one page.
  `list_display` (derived from `_meta.fields`, `admin.py:8`) self-heals.
  Currently `list_filter = ['supplier']` only (`admin.py:12`), so there is
  nothing at risk today, but the next field removal should still check it.
- `SPS_JSON_FIELDS` (feeds the file-preview headers, `functions.py:29-38`) —
  and bump `SPS_JSON_SCHEMA_VERSION` (`functions.py:28`, currently `"1.1"`),
  so a parse cached under the old shape is not served for up to
  `SPS_CACHE_TTL_SECONDS`.

## Imports — the "up, not down" rule has one live exception

`models.py` imports `MainProduct` (`main_product_manager.models`) and
`Supplier`/`Discount` (`supplier_manager.models`) — that direction is clean,
and `main_product_manager/models.py` does not import anything from this app.

**But `main_product_manager/utils.py:20` does:
`from supplier_product_manager.models import SupplierProduct`** — used by
`update_stocks()` (`main_product_manager/utils.py:457-480`) to read the most
recently updated `SupplierProduct` per product. This is a real import back
down, not a stale claim to prune: it works because `utils.py` imports
`.models` (`MainProduct`, already loaded) before reaching into
`supplier_product_manager.models`, and `supplier_product_manager/tasks.py:7`
completes the loop the other way
(`from main_product_manager.utils import compute_supplier_sku,
link_to_local_products`). So the two apps are mutually dependent through
`utils.py` specifically — do not assume "main_product_manager never imports
this app" when touching either side.

`main_product_manager/pim_client.py:5` instantiates `SiteAPI(token=…,
host=…)` at module import — per CLAUDE.md, unset `PIM_TOKEN`/`PIM_HOST` breaks
whatever imports it. Within this app that is **not** `admin.py` (checked: it
only imports `.models` and `.functions`, neither of which reach
`main_product_manager.utils`/`pim_client`) — it is `views.py:44`
(`from .tasks import ...`) → `tasks.py:7`
(`from main_product_manager.utils import ...`) → `main_product_manager/utils.py:18`
(`from .pim_client import site`). So loading `views.py` (which Django's URL
conf does at startup) is what fails, not the admin site specifically.
