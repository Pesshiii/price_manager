---
title: Which rows an import clears and how it matches
summary: source_settings, match_by_article, matching up to whitespace, rename hints.
code: price_manager/supplier_product_manager/functions.py, price_manager/supplier_product_manager/tasks.py
---
# Which rows an import clears and how it matches

## Which rows an import clears — `SupplierProduct.source_settings`

An import clears (NULLs) the fields its setting maps (`Setting.clearable_fields`
for deletion, the payload's columns for imports) only on **its own rows** that
are missing from its file — `functions.own_rows(setting)`:

- rows linked to the setting through `source_settings` (M2M, reverse
  `Setting.supplied_products`) — the settings whose **latest** import contained
  the row, not every setting that ever did;
- plus **nobody's rows**: rows of the supplier linked to no setting at all.

After writing, `_apply` links every written row to the setting and **unlinks**
the rows it just cleared. So a product that moved to another file of the same
supplier is cleared once, then left to the setting that now supplies it —
«ever touched» would make the old setting clear it on every import and the two
imports would flicker. Rows of other settings are never touched: that is what
stopped two settings of one supplier (e.g. stock and prices in separate
files, or two halves of a catalogue) from wiping each other.

Nobody's rows exist on purpose, and in bulk: a setting was deleted (see below),
a row predates `source_settings`, or the supplier's working settings were
replaced by fresh unmapped ones. Handing them to any import of the supplier
keeps the pre-`source_settings` behaviour for them; without it they would never
be cleared again and a supplier re-set-up later would keep frozen stock.

Migration 0015 linked every row to every working setting (≥1 mapped column) of
its supplier. For single-setting suppliers that is exact; for multi-setting
ones the first import of each setting clears and unlinks what is not in its
file — one round of the old behaviour — and the links are exact after that.

**Deleting a setting** (`pre_delete` receiver `release_supplied_products`,
`models.py`) clears its `clearable_fields` on rows no other setting supplies —
a frozen stock is worse than an empty one. It is a signal because settings are
deleted from the mapping screen, the admin and by cascade from `Supplier`.

`apply_counts` uses `own_rows` too, so «нет в файле — обнулятся» in the
confirmation dialog is per setting.

## Matching by article — `Setting.match_by_article`

By default a supplier row is identified by `(article, name)`, because many
suppliers sell variants under one article. `match_by_article` is the opt-in for
suppliers whose articles are unique; `_resolve_by_article` (`functions.py`)
implements it:

- The file is deduplicated **by article**, first row wins; the dropped rows go
  into `duplicates`, and `article_conflicts` is reported with «взята первая
  строка» wording (`duplicate_warning` reads `stats['match_by_article']`).
- Article with **one** existing row → that row is updated; a different name in
  the file **renames** it. The payload carries the old `(article, name)` under
  `RENAME_FROM`; `_apply` renames before the upsert so the upsert (still keyed
  on `(supplier, article, name)`) finds the same pk — the `main_product` link
  and history survive. `apply_counts` counts it as updated, not created+missing.
- Article with **several** existing rows (legacy of the default key) → the data
  goes into all of them, names untouched — the old `ignore_name` behaviour,
  reported as `articles_multi_db`.
- Unknown article → created (with `create_new`) or unmatched.

The DB constraint stays `(supplier, article, name)`; no data migration needed.

## Matching up to whitespace, and rename hints

Every path also finds a row that differs from the file **only by whitespace**
(edges, repeats, tab, NBSP — `_normalize`) and renames it to the file's form
through the same `RENAME_FROM` mechanism, article included:

- default key: `_match_whitespace_variants` — no exact `(article, name)` match,
  and exactly one row of the base normalizes to the file's key and is not
  taken by an exact match of another file row. Several candidates →
  `whitespace_ambiguous`: loaded as new, reported in the warning. It also works
  with «Добавлять новые товары» off (a renamed row counts as matched);
- `match_by_article` and the no-name-column path: `_db_articles` maps a file
  article to the one base article that differs only by whitespace.

`possible_renames` (default key only) counts new file rows whose normalized
article has exactly one row both in the file and in the base, that row not
taken. **Deliberately not transferred automatically**: a variant swap («red»
gone, «blue» added under a single-variant article) looks identical, and moving
the `main_product` link to a different product is worse than clearing — the
catalog would sell the wrong product at another's price. The warning tells the
user to enable «Артикул уникален» if these are real renames. On the
production snapshot there were no such renames at all; the history-free guard
(`missing_linked`) catches a mass rename anyway.
Migration 0014 turned `ignore_name AND create_new` into `match_by_article`
(`ignore_name` without `create_new` never did anything). Its reverse restores
`ignore_name` only on the migrated settings.
