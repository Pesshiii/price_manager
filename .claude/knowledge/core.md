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

`ExecuteLockedTaskAtomicTests` (`core/tests.py:21`) **must** stay a
`TransactionTestCase` — `django.test.TestCase` wraps each test in a transaction,
which would make `connection.in_atomic_block` true inside the runner regardless
of what `atomic=` did. Do not "simplify" it into a `TestCase`.

The cost lands elsewhere. Django truncates **every table** at a
`TransactionTestCase`'s teardown and only restores migration-seeded rows when
`serialized_rollback = True`. So running `core` deletes the `KZT` `Currency` row
that `supplier_manager/migrations/0001_initial.py` seeds. Since CLAUDE.md tells
everyone to run with `--keepdb`, that deletion persists into every later run and
surfaces in a *different* app — 22 `Currency.DoesNotExist` errors raised from
`supplier_product_manager`'s `setUp`, with nothing wrong in the code under test.
CI never reproduces it: it builds the database fresh each run.

Symptom to recognise: an app's tests fail on `--keepdb` but pass without it, in
fixtures rather than assertions. Nothing about `core` will look implicated.

The fix belongs on the consuming side — **no fixture may read a
migration-seeded row.** Use
`Currency.objects.get_or_create(name="KZT", defaults={"value": Decimal("1")})`,
as `supplier_product_manager/tests.py` (`:30`, `:494`, `:571`, `:637`, `:715`)
and `product_price_manager/tests.py:15` now do. Prefer that `defaults=` form
over the inline `get_or_create(name='KZT', value=1)` still at
`main_product_manager/tests.py:53` and `:199`: inline kwargs are *lookups*, so a
KZT row carrying any other value makes get_or_create attempt an INSERT and die
on the unique `name`. `Currency` is the only static seed in the tree — the other
`RunPython` migrations derive rows from existing data — so this list is
currently complete.

`serialized_rollback = True` on the `TransactionTestCase` is the alternative,
and it was rejected: it re-serializes and re-inserts the database around the
class on every run, and it papers over the coupling rather than removing it.

## Gotcha: `core/models/` is an empty directory

There is an empty `core/models/` dir sitting next to `core/models.py`. It has no
`__init__.py` and no files. Python 3 resolves the regular module `models.py`
ahead of a namespace package, so **`core/models.py` is what loads** — it is
harmless today. Do not add files to `core/models/` expecting them to be picked
up; either delete the dir or commit to converting `models.py` into the package
properly. Right now it is just a tripwire.

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

## Dead code

`core/viewmixins.py` → `HtmxMixin` is **unused**. Don't reach for it.
