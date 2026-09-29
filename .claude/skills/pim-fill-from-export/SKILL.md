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

Very wide exports need care: «Мир инструмента» (15 040 rows × 6 996 columns,
most of them empty per row) made pandas write a 4.3 GB JSON with every null
spelled out, and ran for over ten minutes. Rows are therefore written **sparse**
(empty cells omitted — read them with `row.get(col)`); for exports that wide,
reading with `openpyxl` `read_only=True` directly is faster still.

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

A supplier's products may carry a **number suffix** in PIM (*ask*): «Мир
инструмента» articles are `<Код артикула>mi` (`89551` → `89551mi`). Add the
keyed column to the rows (`number_mi`) and match on it alone. The same code
*without* the suffix is often another source's card for the same item
(`89551`, brand RUSSIA) — do not fall back to it, and count those in the report
so the user can decide; the 2026-09-28 run created the `…mi` cards beside them.

### Creating missing products

Only when the user allows it («можно добавлять новые товары»). What the API
demands, learned on that run:

- `POST Product` requires **`status`** (400 «Required property 'status'»
  otherwise); existing supplier cards are `draft`.
- Photos by URL: `POST File {name, url, typeId}` makes PIM download the file,
  then `POST ProductFile {productId, fileId, isMainImage}` links it. The link
  is refused («not allow to link a file of type ''») unless the File has
  `typeId` of the **Image** file type — `Product.files` metadata lists the
  allowed `fileTypes` (`019c320b-77ba-73d3-8f1b-8346dce0f7bb` on this instance).
  *Ask* how many photos per product (the user chose 5, first = main).
- Guard creation by a lookup on `number` so a crash between POST and log never
  duplicates, and resume a product's images from the number already linked.
- Long runs hit `URLError: [SSL: RECORD_LAYER_FAILURE]` from the network, not an
  HTTP code: retry `OSError` too, or the run dies on the first blip (it did,
  twice, after ~1 400 products).
- One photo takes ~2–3 s; 2 914 products with ~10 600 photos took ~9 hours in
  one thread alongside the other runs.

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

The vote counts only each product's **most specific real categories**: an
ancestor of another of its categories is dropped, and so is a childless root
(«Корневая группа», where uncategorised products are parked). Before that rule,
«Корневая группа» won 40 % of the «Мир инструмента» leaves. The CSV shows our
categories as full paths, since leaf names repeat («Сверла»).

Expect the vote to be empty for a new supplier: PIM holds ~36 000
product↔category links for ~280 000 products, essentially the Satu ones. The 2026-09-28 supplier export
(`export_universal_*`, 8 861 matched products, 1 035 leaves) had none, and
only 45 leaves (481 products) matched by name — the rest is a manual mapping
for the user, and the CSV is where it starts.

## 3. Descriptions

**The HTML (detailed) description goes to `longDescription`** («Длинное
описание») — the user's rule, set on the «Мир инструмента» run after a pilot had
put it into `description`. Do not infer the field from filled cards: many carry
HTML in `description` from the earlier Satu run, which is exactly the misleading
signal. `description` stays untouched unless the user names a source for it;
*ask* about any other description column. Copy the text as is (HTML stays HTML).
A product whose target field is already non-empty is not overwritten unless the
user says so — count them in the report.

## 4. Characteristics and units

Follow `reference/attributes.md` — it holds the rules that worked on the first
full run and, above all, **the catalogue already in PIM to reuse** (14 `pm_*`
measures, 9 `g_*` groups, ~360 attributes). Map new source names into existing
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

**Filling only empty attributes** needs the card's current values, and they are
readable one product at a time only: `GET Product/{id}` with
`Flatten-Attributes: true` (keys are the `systemName`s, plus `<code>UnitId`).
A list `GET Product` ignores that header, and `ProductAttributeValue` is not an
endpoint (404). `upsert_values.py` overwrites whatever it is given, so for an
only-empty run do the GET-filter-upsert per product in the writer (one GET per
product; 15 040 products took ~3 h in 4 threads alongside other runs).

Existing values can carry the **right number with the wrong unit** (Satu-era
«Высота подъёма 400 м», «Длина 15 мм» for a 15 m hose, «10 атм» for bar). When
the export has the same number with another unit, *ask*; the user chose to take
the export's unit, 789 values on 763 cards, each logged.

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
