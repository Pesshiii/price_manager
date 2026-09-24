---
title: Import config — Setting, Link, DictItem
summary: The four-model config chain, price and number field constants, removing a mapped field.
code: price_manager/supplier_product_manager/models.py
---
# Import config — Setting, Link, DictItem

## The import config is a four-model chain

`Setting` → `Link` → `DictItem`, plus `SupplierFile` as the upload queue.

- **`Setting`** (`models.py:99`) — one named import profile per supplier.
  `sheet_name`, `index_row` (which row holds the headers), `create_new`
  (create `SupplierProduct`s that don't exist yet), `match_by_article`
  (identity by article alone — see «Matching by article»; replaced
  `ignore_name` in migration 0014).
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
