---
title: Shared template includes
summary: checkbox_field / radio_field facet includes and table_htmx.html, shared by several apps.
code: price_manager/core/templates/core/includes/
---
# Shared template includes

## `core/templates/core/includes/checkbox_field.html` and `radio_field.html` — shared filter-facet includes

Crispy field templates used by every filter panel at least twice per page —
one include per facet, e.g. `ProductFilter` brand + supplier
(`product/filters.py:337,339`). Only `checkbox_field.html` has a swappable
OOB partial; that asymmetry drives the second point below.

**Their inline `<script>` must be idempotent.** htmx executes inline
`<script>`s in swapped content, and classic scripts share one global lexical
scope — a top-level `const`/`let` in an include rendered twice throws
`SyntaxError: Identifier '…' has already been declared` on the second one.
Both guard against this: no top-level declarations, everything gated behind
a `window` flag — `window.__priceManagerCheckboxFilterInit`
(`checkbox_field.html:74-98`) and `window.__priceManagerRadioFilterInit`
(`radio_field.html:89-111`). Any new field include used more than once per
page needs the same guard. Regression test:
`product/tests/test_views.py:220`
`test_filter_panel_scripts_declare_nothing_at_top_level`.

**`checkbox_field.html` can't copy `radio_field.html`'s bind-once pattern.**
Checkbox has a `{% partialdef checkboxes %}` (`:37-71`, `#checkboxes_<auto_id>`)
with an `oob` branch. Its first OOB caller — `OobField` via the stripped
`MainProductFilter.build_helper` of «Привязать из ГП» (`ResolveMainproduct`) —
was removed with that feature on 2026-09-24; the path is live again as the
facet refresh on `/products/` (below). Radio binds once per input and
captures `items` at bind time; that goes stale after an OOB swap — the
already-flagged search input keeps filtering detached nodes. So checkbox instead uses one delegated
`input` listener on `document` (`:90`) that re-queries
`[data-checkbox-filter-item]` on every keystroke, re-applied on `htmx:load`
(`:96`) since the script itself lives outside the partial.

**Per-choice facet counts are opt-in via `field.field.facet_counts`**
(`checkbox_field.html:53-54`, guarded `is not None` not truthy — screens that
never set it, e.g. cart pickers and `MainProductFilter`, must still render).
It's a dict (choice pk → count) [[product]]'s `ProductFilter.narrow_facets`
(`product/filters.py:305-358`) sets on the **bound form's** fields
(`fields['brand']`/`['supplier']`/`['categories']`), not the filter's own
declared field, since django-filter's form is a deep copy. The count sits in
its own `<span>`, not folded into `choice.1`, so `data-checkbox-filter-text`
(quick search) stays the bare name. `#checkboxes_<auto_id>` is the OOB target
of `ProductFilter.build_facets_helper` (`product/filters.py:466-482`), which
re-renders the lists with fresh counts after every filter change on
`/products/`; the quick-search input sits outside the partial and survives.

## `core/templates/core/includes/table_htmx.html` — shared by four tables

Not `core`-only: `core/tables.py` (cart picker), `product_price_manager/tables.py` and
`supplier_product_manager/tables.py` all set
`template_name = 'core/includes/table_htmx.html'` (`django-tables2==2.7.5`).
A change here touches all four. (Five until Phase 2b deleted the old main
page's table; `product/tables.py` — the table behind `/products/` — uses
`django_tables2/bootstrap5.html` directly, not this template.)

**Infinite scroll dies on a hidden last row.** The next-page fetch is wired to
the *last* `<tr>` of the page (`table_htmx.html:40-45`):
`{% if forloop.last and table.page.has_next %}` with
`hx-trigger="intersect once"`. An element with `display:none` has no box, so
`IntersectionObserver` never fires on it. Any feature that hides rows
conditionally (row grouping, collapse/expand, client-side filtering) will
silently stall pagination the moment a page's last row happens to be one of
the hidden ones — no error, no spinner, the list just appears to end. Check
whether the last row of a page can ever be hidden before shipping row-hiding
on any of the four tables.

**Next-page rows land adjacent to the last row, not appended to `<tbody>`.**
`hx-target="this"` + `hx-swap="afterend"` (`table_htmx.html:43-44`) insert
page N+1's rows directly after page N's last row, not at the table's end —
useful for anything needing contiguity across a page boundary (e.g. a group
split across pages): no DOM-reordering script needed, only re-applying
per-row state to the newly arrived rows.

**`Meta.row_attrs` is the per-row hook — reach for it before editing this
template.** `{{ row.attrs.as_html }}` (`table_htmx.html:38`) is computed as
`computed_values(self._table.row_attrs, kwargs=dict(table=self._table,
record=self._record))` (`django_tables2/rows.py:111-113`) — the callable
gets both `record` and `table`, and via `table` can reach
`table.page.object_list` to know a record's page position (e.g. whether
it's the last row, relevant to the trap above), without touching the shared
template that all four tables depend on.

**Column sorting flips the whole declared `order_by` tuple, tie-breakers
included — unless the column defines an `order_FOO` escape hatch.** The `<th>`
builds its sort link from `column.order_by_alias.next` (`table_htmx.html:18`);
`BoundColumn.order_by` returns `order_by.opposite` when the alias is
descending (`django_tables2/columns/base.py:575-580`), and
`OrderByTuple.opposite` — `type(self)(o.opposite for o in self)`
(`django_tables2/utils.py:284`) — negates **every** member, not just the
first, whenever a column relies on the library's default tuple ordering.

It doesn't have to: `BoundColumns.__init__` wires `bound_column.order =
getattr(table, "order_" + name, column.order)`
(`django_tables2/columns/base.py:736`). `TableQuerysetData.order_by` only
calls that hook for the column(s) actually named in the current sort
(`aliases`, `data.py:200-201,211`) — using its queryset directly, skipping
the flip, whenever it returns `(queryset, True)` (`data.py:210-219`; default
`Column.order`, `columns/base.py:388-399`, is a no-op). So a `def
order_pim_id(self, qs, desc): return qs.order_by(('-' if desc else '') +
'pim_id', 'pk'), True` hook on a `Table` would be a tie-break, but it would
only fire when the user sorts **by `pim_id` itself** — it would do nothing
while sorting by any other column (no table in the tree defines this hook
today; it's the shape any future one would need). `modified_any`
(`data.py:198,215,218`) is table-wide too: one hook returning `True` skips
traditional ordering for every column in that sort, not just its own (moot
here since this template only ever sorts by one column at a time). Sorting
also re-renders the whole table (`hx-target= "closest div.table-container"`,
`hx-swap="outerHTML"`, `table_htmx.html:21-22`) and always lands on page 1.
