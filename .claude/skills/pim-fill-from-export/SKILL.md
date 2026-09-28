---
name: pim-fill-from-export
description: Fill AtroPIM product cards from a supplier's or marketplace's export file (Excel/CSV) — first the export's own category tree as a `<Src>Category` entity mapped to our Category, then descriptions, characteristics as attributes, and units. Use when the user attaches an export (Satu, Kaspi, a supplier price list with properties) and asks to «заполнить карточки в PIM», «перенести характеристики/описания в PIM», «загрузить категории выгрузки». Writes to production PIM, always pilot-first and only after the user's «да».
---

# Filling PIM cards from an export

The PIM (`pim.tirado.kz`, AtroCore 2.3.15) is **production**. Every write in
this skill happens only after the user has seen a dry-run report and said yes
to *that* step. Reads are free.

Two rules from the user that override convenience:

- **Transfer, never supplement.** «Данные только переноси, не дополняй.» Nothing
  is invented, completed, translated or rewritten. A value that does not parse is
  skipped and reported, not guessed.
- **Ask where it is unclear.** Every judgment call below is marked *ask*.

## 0. Setup

Work in the session scratchpad; the export and everything derived from it stay
there (never in the repo, a commit, or a PR). `S` below is
`.claude/skills/pim-fill-from-export/scripts` — scripts import `pim.py`, which
reads `PIM_HOST`/`PIM_TOKEN` like `.claude/tools/pim_docs.py`.

```bash
python "$S/export_to_json.py" export.xlsx rows.json
```

The host python may lack `openpyxl`; the docstring of `export_to_json.py` has
the `docker compose cp` route through `celery_worker`. It prints every column
with fill counts and a sample — the base of the profile in step 1.

Before any schema question, consult `pim-docs` or the cached metadata
(`python .claude/tools/pim_docs.py instance metadata entityDefs.<Entity>.fields --keys`).

## 1. Profile the export and report

Identify, and tell the user in one message:

| What | Satu (`export-products-*.xlsx`) | Supplier «universal» (`export_universal_*.xlsx`) |
|---|---|---|
| Product key → PIM field | `Код_товара` → `number` | `okdp` → `number`, then `vendor_code` → `number`, `barcode` → `ean` |
| Category | leaf only: `Идентификатор_подраздела` (= `SatuCategory.code`), `Адрес_подраздела` | full path: `parentid1..4` + `parentid_name1..4` |
| Descriptions | `Описание` (HTML) | `description`, `description_short` |
| Characteristics | repeating triples `Название_/Измерение_/Значение_Характеристики` | wide columns `prop_*` (`prop_length`, `prop_weight_gross`, …) |

New formats: find the same four things. Then match products (read-only):

```bash
python "$S/match_products.py" rows.json found.json Код_товара:number
```

Report found / missing / ambiguous. Ambiguous keys (one key, two PIM products)
are never resolved by guessing — *ask*.

## 2. The export's category tree (`<Src>Category`)

How the instance models this today: one **Hierarchy entity per source** —
`SatuCategory` (6 633 nodes), `TiradoCategory`, `MKSCategory`,
`OtvertkaCategory`, `VICategory`. Each has `name`, `code` (the source's own
category id), `parents`, and a link `category` → our `Category` (reverse side
`Category.<src>Categories`). **Products are not linked to these trees** — the
tree is mapped to `Category`, and that mapping is the point of this step. Do not
add a product-side link (the user decided against it).

`source_categories.py` does all three sub-steps; each is a dry run until
`--apply`, and each `--apply` needs its own «да».

**2a. Entity.** *Ask* for the source's name if it is not obvious (it becomes
`<Src>Category`, e.g. `Ecogr` → `EcogrCategory`).

```bash
python "$S/source_categories.py" schema Ecogr --label "Ecogr"          # plan
python "$S/source_categories.py" schema Ecogr --label "Ecogr" --apply  # after «да»
```

Creates, only what is missing: `POST /api/Entity {code, name, namePlural,
type: Hierarchy}`, then `POST /api/EntityField` for `code` (varchar) and
`category` (link → Category, foreignCode `<src>Categories`), and re-reads
`/api/metadata` to verify. `Entity`/`EntityField` are hidden from OpenAPI but
served by the record controller. **The first real use of this path has not
happened yet** — if the verify line says MISMATCH, stop, show it, and fall back
to asking a PIM admin to create the entity in Entity Manager with that shape.
An existing `<Src>Category` is reused as is.

**2b. Tree.**

```bash
python "$S/source_categories.py" tree Ecogr rows.json \
  --levels parentid1:parentid_name1,parentid2:parentid_name2,parentid3:parentid_name3,parentid4:parentid_name4
python "$S/source_categories.py" tree Satu rows.json --leaf Идентификатор_подраздела   # tree already in PIM
```

Idempotent by `code`: only missing nodes are created, parents before children
(`parentsIds`). A leaf-only export cannot build a tree — if its leaves are unknown
to PIM, *ask* for the source's full category tree file rather than creating
orphan leaves.

**2c. Mapping to our Category.**

```bash
python "$S/source_categories.py" map Ecogr rows.json found.json --levels ...   # writes Ecogr_map.csv
```

For every source leaf it votes over the categories its matched products already
have in PIM (`ProductCategory`). Proposed when the top category holds ≥ 80 % of
the products that have one and ≥ 3 of them (`--min-share`, `--min-products`).
When the products have no category at all, it falls back to a Category with
exactly the leaf's name (unique, case- and «ё»-insensitive), marked «по названию
— проверить» and written only with `--by-name`. Everything else is «вручную».
A node that already has a `category` is never changed without `--overwrite`
(*ask*). Send the CSV with `SendUserFile`, get «да», then rerun with `--apply`.
Inner nodes are not mapped automatically.

Expect the vote to be empty for a new supplier: PIM holds ~36 000
product↔category links for ~280 000 products, essentially the Satu ones. The 2026-09-28 supplier export
(`export_universal_*`, 8 861 matched products, 1 035 leaves) had none, and
only 45 leaves (481 products) matched by name — the rest is a manual mapping
for the user, and the CSV is where it starts.

## 3. Descriptions

*Ask* which export column goes to which Product field — `description`,
`longDescription`, and their `…RuRu` variants all exist and are multilingual;
look at a few filled PIM products first to see which the team uses. Copy the text
as is (HTML stays HTML). A product whose target field is already non-empty is
not overwritten unless the user says so — count them in the report.

## 4. Characteristics and units

Follow `reference/attributes.md` — it holds the rules that worked on the first
full run and, above all, **the catalogue already in PIM to reuse** (14 `pm_*`
measures, 9 `g_*` groups, ~254 attributes). Map new source names into existing
attributes first; create a new attribute / unit only for what has no match, and
list those creations for the user before making them.

Build, in the scratchpad: a spec module (synonyms → attribute, default units,
exclusions), a transform that writes `plan.json`
(`{pid: {"fields": {...}, "attrs": {code: [value, unit]}}}`), a `report.txt`
(per attribute: ok / not parsed / conflicts, with examples) and a `mapping.csv`
for the user. **No network in the transform.** *Ask* about the frequency floor and
about borderline «characteristics» (barcodes, marketing bullets, links).

After «да» to the mapping: an idempotent setup that creates the missing
measures / units / groups / attributes and saves `ids.json`
(`attr`, `unit`, `attr_measure`), bodies in `reference/attributes.md`.

## 5. Pilot, then the full run

Pick ~5 products that cover the edge cases (a unit conversion, a bool, a URL, a
joined text, the product with the most values), write only them, and read back:

```bash
python "$S/upsert_values.py" plan.json ids.json --only PID1 PID2 PID3 PID4 PID5
python "$S/read_back.py" plan.json ids.json PID1 PID2 PID3 PID4 PID5
```

`read_back.py` must print `mismatches 0`; also look at the `…AllUnits` line
(the unit multiplier trap). Send the user a table of card links with what to
check on each, and wait for «запускай».

Full run in the background, watched with `Monitor` on `push.log`:

```bash
python "$S/upsert_values.py" plan.json ids.json            # 1 thread, ~100 products/min
python "$S/upsert_values.py" plan.json ids.json --threads 4  # ~390/min — only if the user asks
```

It resumes from `push.log`, treats 304 as success, retries 3×. Report progress
every ~5 000 products and at once on a `FAIL`. At the end reconcile: products
written vs planned, every `FAIL` line, the unmatched rows from step 1.

## Final report to the user

Counts per step (tree nodes created, nodes mapped / left for manual work,
descriptions written / skipped as non-empty, attributes created, values written),
the not-parsed examples, and links to 3–5 cards. Nothing from the export goes
to Telegram, GitHub or the repo.
