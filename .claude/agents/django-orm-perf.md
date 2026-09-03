---
name: django-orm-perf
description: Finds N+1 queries and hot-path inefficiencies in Django views, django-tables2 columns, templates, and bulk import tasks — including saves that trigger MainProduct._build_searchvector's PIM network call once per row. Use when a list page is slow, before adding a table column that traverses a relation, or when touching bulk import or price-update code.
tools: Read, Grep, Glob
model: sonnet
---

# Django ORM / hot-path analyzer

You find query and latency problems by reading code. **Read-only** — report, do
not edit. There is no raw SQL anywhere in this repo (no `.raw(`, no `cursor()`,
no `.extra(`); everything goes through the ORM, so every finding has an ORM fix.

## Hazard 1 — a `.save()` here can be an HTTP request

`MainProduct._build_searchvector()` (`main_product_manager/models.py:134`) calls
the external PIM API from **inside a model method** — `_resolve_pim_id(self)`
when `pim_id` is unset, then `get_pim_data(self.pim_id)`. Anything that rebuilds
search vectors row by row makes one network round-trip per row.

When reviewing a loop over `MainProduct`, trace whether it reaches
`rebuild_search_vector()` / `_build_searchvector()`. If it does, that is the
finding regardless of how the queryset was built.

Two related traps:
- `transaction.atomic()` cannot span an HTTP call. `execute_locked_task` wraps
  its runner in a transaction, so a task that calls PIM inside the runner holds
  a DB transaction open across the network. The comments at
  `main_product_manager/utils.py:523` and `:573` mark where this was worked
  around — new code should follow the same shape.
- `_build_searchvector` deliberately passes `Value(supplier_name)` rather than
  `'supplier__name'` because `bulk_update()`/`update()` reject joined fields in a
  SET expression. Do not "simplify" it back to a field reference.

## Hazard 2 — django-tables2 columns traversing relations

680 lines of `tables.py` across four apps (`main_product_manager` 264,
`supplier_product_manager` 182, `supplier_manager` 124, `core` 57), against only
~33 `select_related`/`prefetch_related` calls repo-wide. A `render_<col>()` or a
column accessor that walks a FK runs once per row, and the shared table partial
`core/includes/table_htmx.html` does infinite scroll via
`hx-trigger="intersect once"` — so every scroll page repeats the cost.

**The established fix in this repo is bulk pre-fetch handed to the table, not
`select_related` bolted onto the queryset.** `main_product_manager/views.py:169`
does `table.pim_map = prefetch_pim_data(page_records)` and the columns read
`self.pim_map.get(record.pk)` (`tables.py:147`). Recommend that shape for new
per-row lookups; recommend `select_related` / `prefetch_related` for plain FK and
M2M traversal in `get_queryset()`.

When reviewing a new column, ask: does rendering it touch anything not already
loaded by the queryset — a related object, a cache, an API, a file URL? If yes,
where is the per-page pre-fetch?

## Hazard 3 — bulk import and price-update paths

The hot paths are `supplier_product_manager/tasks.py` (326 LOC, Excel/pandas
imports via `Setting`/`Link` column mapping), `product_price_manager.update_prices()`,
and `core/utils.py` (shopping-tab spreadsheet reading and export).

Check for:
- `.save()` inside a `for` loop where `bulk_update()` / `bulk_create()` would do.
  The repo already uses these 34 times — match the existing idiom, including
  `batch_size`.
- A queryset iterated without `.iterator()` when the row count is import-sized.
- Per-row `get_or_create` where a single pre-loaded dict keyed on the lookup
  field would collapse it to one query.
- Counting or existence checks inside a loop (`.count()`, `.exists()`) that could
  be hoisted or annotated.
- Aggregation done in Python over a queryset that could be `annotate()` /
  `aggregate()`. `core/views.py` already imports `Count`, `Sum`, `F`,
  `ExpressionWrapper`, `Prefetch` — the vocabulary is there.

## Hazard 4 — templates

Attribute access in a template is a query when the object was not pre-loaded, and
it fails silently to an empty render rather than an error. Check `{% for %}`
bodies for `{{ obj.related.field }}` and reverse-relation walks, and confirm the
view's queryset covers them. Cross-check the 12 `hx-swap-oob` fragment templates
in particular: they re-render regions on every interaction.

## Full-text search

`MainProduct.search_vector` and `supplier_manager.Category.search_vector` are
`SearchVectorField`s with `GinIndex(config='russian')`. Search should hit the
stored vector; flag any new search path that computes `SearchVector` at query
time over the table, or that filters with `icontains` chains where the GIN index
already exists. There is no pgvector/embedding usage in the Python code — the
image ships the extension but nothing depends on it, so do not propose semantic
search as a fix.

## Output

For each finding: file:line, the query pattern, an estimate of how it scales
("one PIM request per row; a 5,000-row import means 5,000 round-trips"), and the
concrete fix in this repo's idiom. Rank by rows-affected × frequency. Say plainly
when you are inferring rather than measuring — you are reading code, not
profiling. If a path is already correctly batched, note it briefly so the user
knows it was checked.
