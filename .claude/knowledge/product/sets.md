---
title: Product sets («наборы»)
summary: ProductSetItem, sync from PIM, main_values/set_costs, page and export surfacing.
code: price_manager/product/services/sets.py, price_manager/product/set_costs.py, price_manager/product/main_values.py
---
# Product sets («наборы»)

## Product sets («наборы») — PRs #230/#236/#233, 2026-09-24

A "set" is just a `Product` that has `ProductSetItem` rows — **no boolean
flag**. `ProductSetItem` (`models.py:165-209`, migration `0011`) mirrors the
PIM association code `set_components`, one row per set-component pair:
`set_product` FK CASCADE (`related_name='set_items'`), `component` FK
**SET_NULL**, nullable (`related_name='in_sets'`), plus a **snapshot** of the
PIM side (`component_pim_product_id`, `component_number`, `component_name`),
`amount`, `sorting`. Unique on `(set_product, component_pim_product_id)`.

- **Why `component` is nullable + snapshotted, not just an FK:** a set's
  component may be a PIM `Product` no local `Product` matches at all (real
  data: a shelving set's *both* components, and 2 of the electrician kit's 20)
  — the row still has to render and count toward "missing" in the cost/
  buildable numbers, so the PIM number/name travel with the row regardless of
  whether a local match exists.
- **Why SET_NULL, not CASCADE:** deleting a component `Product` must never
  silently shorten someone else's set composition; the row survives as
  "not found" and the next sync re-resolves it.
- **A set can be assembled-in-stock** (has its own `MainProduct`s/PMP, e.g.
  AL10009 in prod — set cost then sits *next to* its own supplier price, not
  instead of it) **or purely virtual** (no suppliers at all). Virtual sets are
  invisible to the rest of the PIM pipeline: `main_product_manager.utils`'s
  `iter_unpushed_product_pk_batches` requires `main_products`, and
  `services/pim_sync.py`'s `unsynced_products()` requires `pim_id` — so a
  virtual set's `Product` is created **only** by `sync_product_sets`, with
  `pim_id` left `NULL`, and content is fed to it from the same sync
  (`apply_pim_product`), not from `sync_product_from_pim`/backfill. Its
  `display_name` falls back straight to `number` (no `MainProduct` to fall
  back to at all).

### Sync — `product/services/sets.py: sync_product_sets()`

Task `product.sync_product_sets` (`execute_locked_task`, `atomic=False` — it's
on the network per set/component), scheduled at 04:00, **after**
`reindex_pim_ids` (`price_manager/settings/celery.py`).

- Reads only the **direct** association (`AssociatedProduct` rows for the
  `Association` whose `code == 'set_components'`) — PIM auto-creates the
  reverse `part_of_set` association too, and its `amount` is always `NULL`,
  so reading it would silently drop quantities.
- **Resolving a PIM product id → local `Product`** (`_candidates`/`_pick`):
  match by PMP `platformID` (= local pk) first, then `number__iexact`
  (case-insensitive per the `Lower('number')` constraint); among several
  candidates prefer one already PMP-linked, then one with `stock > 0`, then
  one with any `MainProduct`, then the lowest pk. A set with **neither** a
  PIM number **nor** a PMP match is skipped (`skipped_sets`), never
  created — creating it would duplicate it on every future run.
- **Composition is fully replaced per set, in its own transaction**
  (`product.set_items.all().delete()` + `bulk_create`) — one bad set can't
  half-write.
- **Pruning of sets that vanished from PIM is skipped for the whole run if
  any set failed to fetch** — a failed fetch is indistinguishable from a
  deletion, and `_fetch_all` (wrapping `pim_api.fetch_list`) raises on a
  truncated page for the same reason: a short listing must not read as
  "these sets no longer exist."
- `amount` from PIM is integer and nullable: `NULL` → `1`; `<= 0` → the link
  is skipped, not zeroed.
- `apply_pim_product(product, data)` (`services/pim_sync.py`) is the
  name/raw_data/brand/categories write step **extracted out of**
  `sync_product_from_pim` specifically so this sync can reuse it for a set's
  own `Product` row.
- **PIM API facts verified live while building this:** `where type='in'`
  works on `PriceManagerProduct.productId` and `Product.id` (list value via
  `pim_api.Where`); `type='equals'` works on `Association.code` and
  `AssociatedProduct.associationId`.

### `product/main_values.py` — the shared "main value" rule, generalized

The level rule that used to live only in `export.py` (`Supplier.price_priority`
/`stock_priority`: first level with a non-zero value wins, `min` for price /
`max` for stock; unranked suppliers form one shared bottom level; rows with no
supplier are last) moved here **unchanged** (`is_zero`, `main_value`,
`cost_key` — `export.py` re-imports them) and gained `level_key` and
`main_row(main_products, attr, priority_field, pick)`, which applies the same
rule directly to a list of `MainProduct` rows and returns `(value, winning
MainProduct)`. `product/tests/test_set_costs.py::MainRowTests::
test_matches_the_main_value_of_the_export` pins that `main_row` agrees with
the export's main value for the same product — this is what lets a set
component's "cost" match what the export would print for it. **Note the
`/products/` «Себестоимость» column is unrelated:** it's a min–max *range*
across all suppliers, ignoring levels entirely — deliberately different from
both the export's main value and a set's component cost.

### `product/set_costs.py` — cost and buildable count for a set

`SetLine` (one `ProductSetItem` + its resolved `cost`/`stock`/`buildable`) and
`SetTotals` (a set's lines + aggregates). Set cost = Σ `amount × component's
main prime_cost` (via `main_row`); buildable = `min(component main stock //
component amount)` across lines. **Components with no cost or no stock data
are excluded from the sum/min but still counted** — `SetTotals.missing_cost`/
`missing_stock` — so the UI can show «нет цены у N из M» instead of
presenting an incomplete sum as if it were the whole set's price.

`set_totals_for(pks)` is **2 queries for any number of sets**
(`ProductSetItem` + `MainProduct`, both `pk__in`), asserted with
`assertNumQueries` in tests. `attach_set_info(products)` (called from
`ProductPage.get_context_data`, `views.py:165`, **after pagination**) sets
`.set_totals` and `.in_sets_count` as plain **attributes** on the page's
`Product` instances — not queryset annotations — because an aggregate over
composition joined into the main `GROUP BY` would drag the 158k-row base
query; `ProductTable`'s `render_*` methods read them via `getattr`, which
works only because cells render lazily, after `get_context_data` has already
attached them.

### Page/UI surfacing

- Badge «Набор» and a «в N наборах» link (to `?contains=<pk>`) in
  `ProductTable.render_display_name` (`tables.py:278-299`).
- «из компл.: …» cost hint under the own prime-cost range,
  `render_prime_cost_range` → `set_cost_html` (`tables.py:301-319`).
- Filters (`filters.py`): `is_set` — a switch/`BooleanFilter` — and a hidden
  `contains` (`NumberFilter`, matches a component's pk) added to
  `Meta.fields`; `contains` is kept in the crispy layout as a **hidden**
  `Field` so that changing any *other* filter doesn't silently drop it from
  the query string.
- `ProductSuppliersView` (the expand panel) passes `set_totals` too
  (`views.py:203`); template `product/partials/set_assembly.html` uses plain
  `<details>`/`<summary>` rather than Bootstrap collapse, because the panel
  itself arrives over HTMX. `suppliers.html` wraps both blocks in
  `.product-suppliers-content {width:max-content; min-width:100%}` — found in
  the browser: without it the assembly row was cut off at the visible width
  because the panel needs to scroll horizontally.
- **A button inside `<summary>` does not toggle the `<details>`** (verified in
  the browser) — the shopping-tab cart button relies on this to add a set
  without expanding it; see [[core]].

### Export — `product/export.py`

Two columns, «Себестоимость из комплектующих» and «Комплектующих без цены»
(`SET_TITLES`, `export.py:74`), are appended to sheet «Товары» **only if** the
export actually contains at least one set — `detect_sets(pks)`
(`export.py:240-242`) runs before headers are built, in both `build()` and the
CSV path (`export.py:420,480`). This matters because existing export tests
assert exact header lists, and a non-set export must produce byte-identical
headers to before. Both the xlsx path and `FullCsvExporter` share the same
`rows()` generator, so set columns behave identically in both formats.
