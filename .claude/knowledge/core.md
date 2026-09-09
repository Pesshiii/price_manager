# core

The UI hub and shared infrastructure. Largest, most template-heavy app:
**102 of the repo's 146 templates** live here, including templates owned by
*other* apps' views (`supplier/`, `manufacturer/`, `currency/`, `category/`,
`main/`, `upload/`, `registration/`). If you are looking for a template and it
isn't under the app that renders it, look here first.

## `execute_locked_task` — every Celery task should route through it

`core/task_runner.py`. Keyword-only signature:

```python
execute_locked_task(task_name=..., lock_ttl=..., runner=..., atomic=True)  # -> dict
```

What it gives you, in order:
1. Redis lock via `cache.add(f"task-lock:{task_name}", ..., timeout=lock_ttl)`
   — atomic; a second runner gets `status="skipped"`, `reason="lock_exists"`.
2. `runner()` inside `transaction.atomic()` — **unless `atomic=False`**, which
   runs it in autocommit. Only the transaction is dropped; steps 1, 3 and 4
   are unaffected, so the Redis lock still guarantees a single runner.
3. A `TaskRunHistory` row for **every** outcome — success, error, *and*
   lock-skipped — with `duration_ms` and `updated_count`.
4. `cache.delete(lock_key)` in `finally`.

The skipped path `return`s at `:54`, **before** the `try` — so the `finally` at
`:100` never runs for it and a lock-loser cannot delete the winner's lock.

Errors are logged **and re-raised** (`:99`) — it is not a swallow-all wrapper.
A task that wants to notify on failure must wrap the call itself; see
`core/tasks.py:52`–`58`.

`_normalize_updated_count` (`task_runner.py:14`) decides what `updated_count`
becomes: an int/float is cast, a tuple is **summed over its numeric members**,
anything else (including a dict or a model instance) becomes **0**.

The trap this sets: a runner returning a summary like
`{"updated": 42, "skipped": 3}` records **0**, and the obvious fix —
`return (42, 3)` — records **45**, a silently wrong metric that is worse. The
tuple branch is only correct when every member counts the same thing (that is
why `create_pim_links` returning `len(result), created`,
`main_product_manager/utils.py:530`, is fine). **Return the one bare int you
actually want counted.**

The rest of a dict return is not lost: the success path writes
`details={"result": str(result)}` (`:75`). That is a Python **repr string**
inside a `JSONField`, not structured JSON — reading it back needs
`ast.literal_eval`, not `json.loads`. (`error` is populated only on the error
path; `details` is left `{}` there.)

Three consequences worth remembering:
- `task_name` is the lock identity, independent of the Celery
  `@shared_task(name=...)`. Tasks meant to run in parallel need uniquified
  names — see the batch fan-out in [[main_product_manager]].
- A transaction must not span an HTTP call, and moving the *write* after the
  API loop does **not** achieve that — the transaction opens here, before the
  runner is ever entered, so it is held for the whole loop no matter where the
  write sits. `atomic=False` is the only thing that actually drops it. The two
  PIM scans in [[main_product_manager]] use it.
- A runner that `.delay()`s subtasks inside the transaction queues them on
  Redis **immediately**, while its own DB writes can still roll back — the
  subtask then runs against rows that never committed. Use
  `dispatch_after_commit()` (`task_runner.py:24`) instead; the
  `reindex_pim_ids_task` fan-out in `main_product_manager/tasks.py:174` was
  converted to it and is the worked example.

## Trap: running `core` empties the DB for every later `--keepdb` run

`ExecuteLockedTaskAtomicTests` (`core/tests.py:21`) must stay a
`TransactionTestCase` — `TestCase` wraps each test in a transaction, which
would make `connection.in_atomic_block` true regardless of `atomic=`. Django
truncates **every table** at a `TransactionTestCase`'s teardown and only
restores migration-seeded rows when `serialized_rollback = True` (not set
here, deliberately — re-serializing the whole DB on every run just papers
over the coupling rather than removing it). So running `core`'s tests deletes
the `KZT` `Currency` row seeded by `supplier_manager/migrations/0001_initial.py`;
since CLAUDE.md says to run with `--keepdb`, that deletion persists into later
runs and surfaces as 22 `Currency.DoesNotExist` errors from
`supplier_product_manager`'s `setUp` — in a *different* app, with nothing
wrong in the code under test. CI never reproduces it (fresh DB every run).
Symptom to recognise: an app's tests fail on `--keepdb` but pass without it,
in fixtures rather than assertions.

The fix is on the consuming side — no fixture may read a migration-seeded
row. Use `Currency.objects.get_or_create(name="KZT", defaults={"value":
Decimal("1")})`, as `supplier_product_manager/tests.py` (`:30`, `:494`,
`:571`, `:637`, `:715`) and `product_price_manager/tests.py:15` do. The
inline `get_or_create(name='KZT', value=1)` still at
`main_product_manager/tests.py:53`/`:199` is fragile: inline kwargs are
*lookups*, so a KZT row carrying any other value makes it attempt an INSERT
and die on the unique `name`. `Currency` is the only static seed in the tree.

## Models (`core/models.py`)

- `CartItem:6` — `search_query`, M2M `products`, FK `confirmed_product`,
  `quantity`. `confirmed_price`/`line_total` are properties (`:30`, `:37`).
- `ShoppingTab:44` — named tab, `file`, M2M `items`, `open` flag.
- `ShoppingTabExport:65` — generated export file + `rows_count`.
- `PersistentNotification:99` — user-facing notification with `level`
  (`LevelChoices:93`), optional `link`/`link_text`.
- `TaskRunHistory:131` — written by `execute_locked_task`, never by hand.
  `status` from `StatusChoices:126`.
- Gotcha: `core/models/` (empty dir, no `__init__.py`) sits next to this
  file; Python resolves the module first, so `core/models.py` loads — don't
  add files there expecting them to be picked up.

## Middleware (`core/middleware.py`)

`LoginRequiredMiddleware` — global login gate; **everything behind `/` requires
login**. Exemptions: `STATIC_URL`/`MEDIA_URL` prefixes, `settings.LOGIN_URL`,
`LOGIN_EXEMPT_URLS`, `LOGIN_EXEMPT_API_PREFIXES`, and `/admin/login`,
`/admin/logout` (hardcoded, so the stock admin login still works). Requests
under `/api/` get a **401 JSON** response rather than a redirect
(`middleware.py:46`) — worth knowing when an API client reports a redirect loop.

`toaster_middleware` — if the messages storage is non-empty, fires a
`toasts:fetch` client event `after="settle"`. Adapted from Josh Karamuth's
django-messages-toast-htmx pattern (credited in the docstring).

## Views (`core/views.py`, ~640 lines)

The shopping-tab / cart feature is the whole file. `ShoppingTab*` — list, delete,
detail, export, export-download, import + preview + run (`:103`–`:364`).
`CartItem*` — add, detail, quick-add, confirm, unconfirm, remove, product-select,
add-products (`:365`–`:634`). Plus `PersistentNotification*` (`:55`, `:71`),
auth views (`:84`, `:99`), `InstructionsView` and `mainpage`.

Templates in `core/templates/shopping_tab/` use the **`hx-swap-oob`** convention
throughout, not the modal-CRUD one — one action refreshes a status chip, a
summary panel and a list together without a reload. See the `htmx-oob-fragments`
skill. `_shopping_tab_summary` (`:176`) and `_get_shopping_tab_items` (`:168`)
are the helpers those fragments render from.

**The shopping-tab stock badge cannot distinguish "out of stock" from "never
synced".** `core/templates/shopping_tab/includes/stock_badge.html:2-8`
branches on `{% if product.stock %}`, and Django template truthiness makes
both `None` and `0` falsy, so a `MainProduct` whose stock has never been
synchronised renders identically to one genuinely out of stock — it shows
`product.supplier.msg_navailable` (default «Нет в наличии»,
`supplier_manager/models.py:90`).

This matters because [[main_product_manager]] treats `stock IS NULL` as a
distinct third state and defends it deliberately on the write path:
`update_stocks` filters on `Q(stock__isnull=True) | ~Q(stock=F('new_stock'))`
(`main_product_manager/utils.py:407`) precisely so never-synced products are
not permanently skipped, and the rule is pinned by
`UpdateStocksNullSafeTests` (`main_product_manager/tests.py:51`). The
distinction is enforced on the write path and dropped on every read path: the
two equivalent renderers on the read side —
`render_stock_msg` in `main_product_manager/tables.py:117-123` and
`Supplier.get_delivery_days_for_stock` in `supplier_manager/models.py:97-100`
— carry the same `if not record.stock` / `if stock and stock > 0`
conflation the template comment gestures at when it says the texts are «те
же, что в главном прайсе». Those two are being fixed under issue #155; **this
badge is explicitly out of that issue's scope** and stays as-is. If the cart
is ever revisited, it needs its own decision about what a null stock should
say — it isn't inherited for free from whatever #155 lands on.

## `core/templates/core/includes/table_htmx.html` — shared by five tables

Not `core`-only: `core/tables.py:25`, `main_product_manager/tables.py:113` and
`:206`, `product_price_manager/tables.py:18`, `supplier_product_manager/tables.py:75`
all set `template_name = 'core/includes/table_htmx.html'`
(`django-tables2==2.7.5`, `price_manager/requirements.txt:37`; verified
against `venv/Lib/site-packages/django_tables2/`). A change here touches all five.

**Infinite scroll dies on a hidden last row.** The next-page fetch is wired to
the *last* `<tr>` of the page (`table_htmx.html:40-45`):
`{% if forloop.last and table.page.has_next %}` with
`hx-trigger="intersect once"`. An element with `display:none` has no box, so
`IntersectionObserver` never fires on it. Any feature that hides rows
conditionally (row grouping, collapse/expand, client-side filtering) will
silently stall pagination the moment a page's last row happens to be one of
the hidden ones — no error, no spinner, the list just appears to end. Check
whether the last row of a page can ever be hidden before shipping row-hiding
on any of the five tables — this is exactly the trap issue #155
([[main_product_manager]], collapsing `MainProduct` rows by `pim_id`) has to
navigate.

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
template that all five tables depend on.

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
`Column.order`, `columns/base.py:388-399`, is a no-op). So `def
order_pim_id(self, qs, desc): return qs.order_by(('-' if desc else '') +
'pim_id', 'pk'), True` on the `Table` is a tie-break, but it only fires when
the user sorts **by `pim_id` itself** — it does nothing while sorting by any
other column. `modified_any` (`data.py:198,215,218`) is table-wide too: one
hook returning `True` skips traditional ordering for every column in that
sort, not just its own (moot here since this template only ever sorts by one
column at a time). Sorting also re-renders the whole table (`hx-target=
"closest div.table-container"`, `hx-swap="outerHTML"`, `table_htmx.html:21-22`)
and always lands on page 1.

## Dead code

`core/viewmixins.py` → `HtmxMixin` is **unused**. Don't reach for it.
