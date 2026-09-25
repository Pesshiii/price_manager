---
title: Known open problems in the import
summary: Import problems that are known and not fixed yet.
code: price_manager/supplier_product_manager/functions.py, price_manager/supplier_product_manager/models.py
---
# Known open problems in the import

Recorded so the next person does not rediscover them; each needs a design
decision, not a quick patch.

- **The same product in two files with the same field** (two warehouses): the
  value is whatever the last import wrote. `source_settings` scopes clearing,
  not values; summing stock across warehouses would be a separate feature.
- **Identity is `(supplier, article, name)`** (`models.py:86-90`). A supplier
  fixing a typo in a name creates a new row and nulls the old one, which loses
  its `main_product` link — **unless** the file's new name differs from the
  stored one only by whitespace, in which case whitespace matching
  (see [[supplier_product_manager/matching]]) renames the row in place instead.
  **Do not "fix" this by switching the key to `(supplier, article)` for
  everyone.** Checked on the production snapshot: renames are almost
  nonexistent, while thousands of articles legitimately carry several *live*
  rows with different names **and different prices** — variants (length, size,
  colour) sold under one supplier article, most of them already linked to
  separate `MainProduct`s. An article-only key would keep one variant per
  article and null the rest on the next import. The by-article key therefore
  exists only as the per-`Setting` opt-in `match_by_article`
  (see [[supplier_product_manager/matching]]); by default the import **warns**
  about `article_conflicts` instead.
- **Stored articles and names carry leading/trailing whitespace** — common in
  production. `get_df` now strips every cell (`functions.py:271`, and a
  whitespace-only cell is empty, so a column of blanks drops out like an empty
  one). Stored rows with edge spaces are renamed in place by whitespace
  matching (see [[supplier_product_manager/matching]]) on their next import —
  the first import of a supplier that stored every article with a trailing
  space renames all its rows, which is why `_rename_rows`
  (`functions.py:1114`) is one `bulk_update`, not an `UPDATE` per row. Left
  over, deliberately:
  - `MainProduct.sku` copied from such articles keeps the space. It was **not**
    trimmed: sku is what links a MainProduct to its local `Product.number` and
    through it to the PIM record, so trimming sku alone would split them, and
    stripping does not meaningfully raise PIM coverage (see [[product]]).
    New copies get clean skus because the articles are clean now.
  - pairs of rows that already differ only by whitespace, both linked to
    *different* `MainProduct`s, need a manual decision.
- **Numbers** go through `_parse_number` (`functions.py:617`): thousands
  separators (space, NBSP, `.`/`,` — the later of the two is decimal, a lone
  `,` is decimal), currency, `шт`, and lower bounds (`>10`, `10+`, `более 10`
  → 10). Upper bounds and ranges (`<5`, `до 5`, `10-20`) and words are **not
  guessed**: they stay empty and are counted per field in `unparsed_numbers`
  (with examples) — in the notification's warning, `ImportRun.unparsed_numbers`
  and «Разбор файла». A dash placeholder (`-`, `—`) is empty, not unparsed. A
  row whose every mapped value is empty is still dropped and nulled as
  "missing".
- **`DictItem` replacement is substring-based** (`str.replace`,
  `functions.py:518`), so «в наличии → 10» also rewrites «нет в наличии».
- **Parsing is read-only.** `resolve_conflicts` (`functions.py:196`) used to
  run inside `get_sps`: before the guard, and even for an import that was
  then refused or held, it created a whitespace-cleaned copy of every row
  with a tab, line break or NBSP in the name. The file's cleaned name then
  matched the copy, and the original — the row linked to a `MainProduct` —
  was nulled as missing. It survives only as the `SupplierProductAdmin`
  action (`admin.py:13-17`).
