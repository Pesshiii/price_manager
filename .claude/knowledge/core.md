# core

The UI hub and shared infrastructure. Largest, most template-heavy app:
**81 of the repo's 123 templates** live here, including templates owned by
*other* apps' views (`supplier/`, `currency/`, `main/`, `upload/`,
`registration/`). The `category/` and `manufacturer/` folders went with Phase
2b-3 — they had had no routes for a while. If you are looking for a template and it
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

The skipped path `return`s at `:84`, **before** the `try` — so the `finally` at
`:133` never runs for it and a lock-loser cannot delete the winner's lock.

Errors are logged **and re-raised** (`:131`-`:132`) — it is not a swallow-all
wrapper. A task that wants to notify on failure must wrap the call itself;
see `core/tasks.py:51`–`59` (`update_cart_items_task`'s `try`/`except` around
the `execute_locked_task()` call).

`_normalize_updated_count` (`task_runner.py:14`) decides what `updated_count`
becomes: an int/float is cast, a tuple is **summed over its numeric members**,
anything else (including a dict or a model instance) becomes **0**.

The trap this sets: a runner returning a summary like
`{"updated": 42, "skipped": 3}` records **0**, and the obvious fix —
`return (42, 3)` — records **45**, a silently wrong metric that is worse. The
tuple branch is only correct when every member counts the same unit, as
`update_prices` (`product_price_manager/models.py:455`, passed straight as
`runner=` by both apps' `update_prices_task`) does: both members of its
`(count, dcount)` are counts of `MainProduct` rows written, so summing them
is correct. [[main_product_manager]]'s `reindex_pim_ids_task` shows the trap
from the other side: it used to return `(numbered, linked)` — Products
numbered and MainProducts linked, not the same unit — and was changed to a
bare `linked`, with a comment at the call site naming this exact trap
(`main_product_manager/tasks.py:155-157`); the function its batch task runs,
`push_pim_links` (`main_product_manager/utils.py:755`), returns a plain int
and raises `PimScanError` on failure rather than folding a failure count into
the total. **Return the one bare int you actually want counted.**

The rest of a dict return is not lost: the success path writes
`details={"result": str(result)}` (`:108`). That is a Python **repr string**
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
  write sits. `atomic=False` is the only thing that actually drops it. In
  [[main_product_manager]] that's `reindex_pim_ids_batch_task`
  (`tasks.py:166-175`), the HTTP-bound batch — its parent `reindex_pim_ids_task`
  stays atomic on purpose, since its own runner does only local DB work
  (backfill numbers, link/create `product.Product` rows) before dispatching.
- A runner that `.delay()`s subtasks inside the transaction queues them on
  Redis **immediately**, while its own DB writes can still roll back. Use
  `dispatch_after_commit()` (`task_runner.py:24`) instead — CLAUDE.md's
  "Dispatching a subtask" paragraph has the why. The `reindex_pim_ids_task`
  fan-out in `main_product_manager/tasks.py:145-150` is the worked example.

## Trap: running `core` empties the DB for every later `--keepdb` run

`ExecuteLockedTaskAtomicTests` (`core/tests.py:35`) must stay a
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
Decimal("1")})`, as `supplier_product_manager/tests.py` (`:60`, `:561`,
`:645`, `:713`, `:799`) and `product_price_manager/tests.py:15` do. The
inline `get_or_create(name='KZT', value=1)` still at
`main_product_manager/tests.py:14`/`:106`/`:255`/`:478` is fragile: inline
kwargs are *lookups*, so a KZT row carrying any other value makes it attempt
an INSERT and die on the unique `name`. `Currency` is the only static seed in
the tree.

## Models (`core/models.py`)

- `CartItem:6` — `search_query`, M2M `products`, FK `confirmed_product`,
  `quantity`. `confirmed_price`/`line_total` are properties (`:30`, `:37`).
- `ShoppingTab:44` — named tab, `file`, M2M `items`, `open` flag.
- `ShoppingTabExport:65` — generated export file + `rows_count`.
- `PersistentNotification:99` — user-facing notification with `level`
  (`LevelChoices:93`), optional `link`/`link_text`.
- `TaskRunHistory:131` — written by `execute_locked_task`, never by hand.
  `status` from `StatusChoices:126`.

## Middleware (`core/middleware.py`)

`LoginRequiredMiddleware` — global login gate; **everything behind `/` requires
login**. Exemptions: `STATIC_URL`/`MEDIA_URL` prefixes, `settings.LOGIN_URL`,
`LOGIN_EXEMPT_URLS`, `LOGIN_EXEMPT_API_PREFIXES`, and `/admin/login`,
`/admin/logout` (hardcoded, so the stock admin login still works). Requests
under `/api/` get a **401 JSON** response rather than a redirect
(`middleware.py:46`) — worth knowing when an API client reports a redirect loop.

`LOGIN_EXEMPT_URLS` entries are **URL names**, not raw paths: the middleware
resolves each via `resolve_url()` once at `__init__` into a path set
(`middleware.py:21-24,69-79`), then does an exact `path in self.exempt_paths`
check per request (`:57`). `'bitrix24-login'`/`'bitrix24-callback'` were added
here (`settings/messages.py:19-20`) alongside `'login'`/`'logout'`/`'admin:*'`.

`toaster_middleware` (`:149-165`) — if `django.contrib.messages` storage is
non-empty, adds `HX-Trigger-After-Settle: toasts:fetch` to the response via
`trigger_client_event(..., after="settle")`. Adapted from Josh Karamuth's
django-messages-toast-htmx pattern (credited in the docstring). The listener
is `core/templates/base.html:34` — `hx-get="{% url 'toast-messages' %}"
hx-trigger="toasts:fetch from:body"`.

**A 204 response never shows its pending message as a toast.** HTMX does no
swap on 204 (`HX-Swap: none` semantics are implicit — no content, nothing to
settle), so `htmx:afterSettle` never fires and the `HX-Trigger-After-Settle`
header is never acted on; the message stays in the session and only surfaces
on the *next* full page load, not the action that produced it. Fix: return an
empty **200** (`HttpResponse()`) instead of `HttpResponse(status=204)`, paired
with `hx-swap="none"` on the triggering element — the swap is a no-op but
settle still happens. `HttpResponseClientRefresh` actions are unaffected
(the reload itself re-renders the message). Worked example:
`product/views.py:217-241` `ProductExportView` — its docstring (`:226-230`)
states the same reasoning after the view was changed from 204 to 200; see
[[product]] for the export feature itself.

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
with an `oob` branch. Its only OOB caller — `OobField` via the stripped
`MainProductFilter.build_helper` of «Привязать из ГП» (`ResolveMainproduct`) —
was removed with that feature on 2026-09-24, so the `oob` path is dormant, not
dead: keep it if a partial re-swap comes back. Radio binds once per input and
captures `items` at bind time; that goes stale after an OOB swap — the
already-flagged search input keeps filtering detached nodes. So checkbox instead uses one delegated
`input` listener on `document` (`:90`) that re-queries
`[data-checkbox-filter-item]` on every keystroke, re-applied on `htmx:load`
(`:96`) since the script itself lives outside the partial.

## Views (`core/views.py`, ~711 lines)

The shopping-tab / cart feature is the whole file. `ShoppingTab*` — list, delete,
detail, export, export-download, import + preview + run (`:173`–`:471`).
`CartItem*` — detail, quick-add, confirm, unconfirm, remove, product-select,
add-products (`:472`–`:705`). Plus `PersistentNotification*` (`:65`, `:81`),
auth views (`:94`, `:114`), Bitrix24 login (`:123`, `:141`, mechanism below),
and `mainpage`. The user guide is not a page here any more — it is
release 0.0 in `releases` (data migration `0002`).

Templates in `core/templates/shopping_tab/` use the **`hx-swap-oob`** convention
throughout, not the modal-CRUD one — one action refreshes a status chip, a
summary panel and a list together without a reload. See the `htmx-oob-fragments`
skill. `_get_shopping_tab_items` (`:238`) and `_shopping_tab_summary` (`:247`)
are the helpers those fragments render from.

**The shopping-tab stock badge cannot distinguish "out of stock" from "never
synced".** `core/templates/shopping_tab/includes/stock_badge.html:2-8`
branches on `{% if product.stock %}`, and Django template truthiness makes
both `None` and `0` falsy, so a `MainProduct` whose stock has never been
synchronised renders identically to one genuinely out of stock — it shows
`product.supplier.msg_navailable` (default «Нет в наличии»,
`supplier_manager/models.py:85-86`).

This matters because [[main_product_manager]] treats `stock IS NULL` as a
distinct third state and defends it deliberately on the write path:
`update_stocks` filters on `Q(stock__isnull=True) | ~Q(stock=F('new_stock'))`
(`main_product_manager/utils.py:493`) precisely so never-synced products are
not permanently skipped, and the rule is pinned by
`UpdateStocksNullSafeTests` (`main_product_manager/tests.py:12`). The two
read-side renderers that used to conflate `None` and `0` the same way — the
old `main_product_manager/tables.py` `render_stock_msg` and
`Supplier.get_delivery_days_for_stock` — were **fixed under issue #155**:
the table moved to `product/tables.py:261-271`
(`SupplierRowTable.render_stock_msg`, now branches on `record.stock is None`
before touching the supplier) and `Supplier.get_delivery_days_for_stock`
(`supplier_manager/models.py:105-118`) now has an explicit `if stock is None`
branch with a docstring explaining why that is a third state, not a synonym
for "no stock". **This cart badge was out of that issue's scope and was not
touched** — it still conflates `None` and `0` via the plain-truthy
`{% if product.stock %}`. If the cart is ever revisited, it needs its own
fix; it doesn't inherit one for free from what #155 already shipped
elsewhere.

## Bitrix24 login — mechanism (CLAUDE.md's `core` bullet covers purpose/policy)

`core/bitrix24.py` + `bitrix24_login`/`bitrix24_callback` (`core/views.py:123`,`:141`).

- `login()` after the hand-rolled exchange needs `user.backend` set by hand
  (`views.py:168`) — no `authenticate()` call happened, so Django can't infer
  it; omitting it raises `ValueError`.
- OAuth `state` is compared as **bytes** —
  `secrets.compare_digest(state.encode(), expected_state.encode())`
  (`views.py:155-157`) — because `compare_digest` raises `TypeError` on a
  non-ASCII `str`; pinned by `test_non_ascii_state_is_refused_not_a_500`
  (`tests.py:283`).
- `_get_json` (`bitrix24.py:49-76`) logs only `type(exc).__name__`, never
  `str(exc)`, on a `requests.RequestException` — urllib3's message embeds the
  full request URL, and the query string carries `client_secret`/`access_token`.
- The callback URL doubles as the Bitrix app's **install URL**
  (`views.py:145-148`): Bitrix POSTs install-time tokens there; the view
  answers 200 and stores nothing — why it's `@csrf_exempt` (`:139`).
- Tests fake the network with a URL-dispatching `side_effect` on
  `core.bitrix24.requests.get` (`_fake_bitrix24`, `tests.py:190-204`) rather
  than patching `exchange_code`/`fetch_current_user` — so the portal-endpoint
  check and request params get exercised, not assumed.
- Login vs link is decided by **session state**, not by what the lookup finds:
  `bitrix24_callback` passes `link_to=request.user` when someone is logged in,
  and `resolve_user` then only calls `link()` — it can refuse, never switch
  users. Refusals in link mode go back to `bitrix24-link`, not `login` (which
  would bounce a logged-in user straight to the main page).
- `user.current` returns `ID` as a **string**; `resolve_user` casts it and
  refuses a non-positive/unparseable one before any lookup.
- A race on the unique `bitrix_user_id` (two first logins at once) is caught as
  `IntegrityError` inside a savepoint in `link()`/`_create_user()`; the loser's
  freshly created user is rolled back and both end up in the winner's account.
- `Bitrix24LinkRequiredMiddleware` answers htmx with `HX-Redirect` (a 302 would
  be swapped into the fragment) and takes `next` from `HX-Current-URL`, since the
  htmx request path is a fragment. `toast-messages` is exempt: the link page's
  own toasts would otherwise trigger a fetch that redirects back to it.
- Keepdb trap met while testing this: a test DB kept from **another branch**
  holding an extra table with an FK to `auth_user` makes every
  `TransactionTestCase` flush fail with «cannot truncate a table referenced in a
  foreign key constraint». Not the code — rerun without `--keepdb`.

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

## Dead code

`core/viewmixins.py` → `HtmxMixin` is **unused**. Don't reach for it.
