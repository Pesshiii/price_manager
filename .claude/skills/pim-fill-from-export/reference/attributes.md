# Characteristics → PIM attributes: the rules that held

Distilled from the 2026-09-28 Satu run (36 100 rows, 7 236 distinct characteristic
names → 254 attributes, 229 963 values on 30 689 products, zero write errors).

## What already exists in PIM — reuse it

That run created the catalogue every later export should map *into*, not beside:

- **14 Measures** with codes `pm_length`, `pm_mass`, `pm_power`, `pm_voltage`,
  `pm_freq`, `pm_volume`, `pm_rpm`, `pm_pressure`, `pm_angle`, `pm_period`,
  `pm_force`, `pm_noise`, `pm_speed`, `pm_qty`, with 27 units.
- **9 AttributeGroups**: `g_dims` «Размеры и вес», `g_pack` «Упаковка», `g_mat`
  «Материалы и исполнение», `g_elec` «Электрика и двигатель», `g_perf`
  «Технические параметры», `g_general` «Общие», `g_set` «Комплектация», `g_lift`
  «Грузоподъёмное оборудование», `g_media` «Документы и медиа».
- **~254 Attributes** on Product, all on panel `attributeValues`, keyed by
  `systemName` (`length`, `weight`, `power`, `warranty`, `barcode`, `benefits`, …).

Dump the live catalogue before mapping, don't trust this list:

```python
from pim import get_all
get_all('Attribute', select='id,name,systemName,type,measureId,attributeGroupId')
get_all('Unit', select='id,code,name,symbol,measureId,multiplier,isMain')
```

Leave alone: the demo Measures `dimension`/`currency` and their units, and the
`setProducts` attribute («Set Products», used by price_manager's sets).

## Mapping table (spec)

Write it as a Python module in the scratchpad, one entry per target attribute:

```python
t('length', 'Длина', 'float', 'pm_length', 'g_dims',
  {'Длина': 'мм', 'длина, мм': 'мм', 'Длина (мм)': 'мм', 'длина, м': 'м'})
```

`{source name: default unit}` — the default is used only when neither the unit
column nor the value itself names a unit. Plus `UNIT_ALIASES` (symbol → measure,
unit) and `EXCLUDED` (name → why it is not a characteristic).

- **Merge synonyms** into one attribute: `Вес` / `Вес (кг)` / `Масса изделия`;
  `Гарантия` / `Срок гарантии` / `Гарантийный срок`.
- **Frequency floor.** Names present on fewer than ~100 products were not
  imported (the user chose that). Report how much the floor drops; ask again for
  each new export — it is the user's call, not a constant.
- **Not characteristics**, excluded by default: stock (`В наличии:`), the
  product name repeated, the article number. Barcodes, marketing bullets and
  links were first excluded, then brought back on request as `barcode`,
  `benefits` (text, several bullets joined with newlines), `video`, `manual_url`,
  `certificate`… — ask, don't decide.

## Value conversion

- Numbers: `1 000` → 1000, `,` → `.`, `3/4"` → 0.75 inch; the unit from the unit
  column, else from the value's tail, else the source's default.
- **Unparseable → skipped and reported, never guessed**: ranges `250-260`,
  `5 /`, `не установлен`, `2 вперед/1 назад`. The user sees them in the report.
- Warranty: `2 года` → 24 months, `12 мес.` → 12.
- bool: `да/есть/1` → true, `нет/0` → false, anything else skipped.
- url: bare 11-char YouTube id → full watch URL; not `http(s)://…` → skipped.
- varchar > 255 chars → skipped (or make the attribute `text`).
- Two source names feeding one attribute with different values on one product:
  first wins, count the conflicts per attribute in the report (weight had 687).
- Ambiguous defaults need a heuristic, and the heuristic goes in the report:
  weight without unit ≥ 50 on a product whose name says «г» → grams; volume
  without unit → the unit written in the product name, else ≥100 → мл.

## Units: the multiplier trap

`Unit.multiplier` is **the size of this unit in main units**: main `kg` = 1,
`g` = 0.001, `t` = 1000. The first run set it inverted and 60 g displayed as
60 000 kg — the values were right, the conversion was not. After creating units,
read a pilot product flattened (`Flatten-Attributes: true`) and check
`<code>AllUnits` (`read_back.py` prints it).

## Creation bodies that worked

```python
POST Measure        {'name', 'nameRuRu', 'code'}
POST Unit           {'name', 'nameRuRu', 'code', 'symbol', 'measureId', 'isMain', 'multiplier', 'isActive': True}
POST AttributeGroup {'name', 'nameRuRu', 'code', 'entityId': 'Product', 'sortOrder'}
POST Attribute      {'name', 'nameRuRu', 'entityId': 'Product', 'systemName', 'type',
                     'attributePanelId': 'attributeValues', 'attributeGroupId', 'sortOrder',
                     # numeric with unit:
                     'measureId', 'defaultUnit': <main unit id>}
POST Product/{id}/upsertAttributeValues  [{'attributeId', 'value', 'valueUnitId'?}, ...]
```

Setup must be idempotent: look each thing up by `code`/`systemName` first,
create only what is missing, save ids to `ids.json` after each create.
