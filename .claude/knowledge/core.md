# core

The UI hub and shared infrastructure. Largest, most template-heavy app:
**102 of the repo's 146 templates** live here, including templates owned by
*other* apps' views (`supplier/`, `manufacturer/`, `currency/`, `category/`,
`main/`, `upload/`, `registration/`). If you are looking for a template and it
isn't under the app that renders it, look here first.

## `execute_locked_task` — every Celery task should route through it

`core/task_runner.py`. Keyword-only signature:

```python
execute_locked_task(task_name=..., lock_ttl=..., runner=...)  # -> dict
```

What it gives you, in order:
1. Redis lock via `cache.add(f"task-lock:{task_name}", ..., timeout=lock_ttl)`
   — atomic; a second runner gets `status="skipped"`, `reason="lock_exists"`.
2. `runner()` inside `transaction.atomic()`.
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
`main_product_manager/utils.py:527`, is fine). **Return the one bare int you
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
- `transaction.atomic()` cannot span an HTTP call. A runner that calls PIM
  holds a transaction open across the network.
- A runner that `.delay()`s subtasks inside that `transaction.atomic()` (`:57`)
  queues them on Redis **immediately**, while its own DB writes can still roll
  back — the subtask then runs against rows that never committed.
  `main_product_manager/tasks.py:167`–`170` does exactly this.

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
