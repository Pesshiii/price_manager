# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Start everything:**
```bash
docker compose up --build
```
App runs at `http://localhost:8000` (or `$WEB_PORT`, if you are running a second stack — see below). Everything behind `/` requires login (see `core.middleware.LoginRequiredMiddleware`).

**Run tests (local venv is broken — always use Docker):**
```bash
docker compose exec -T celery_worker python manage.py test <app_label> --keepdb
# Example: single app
docker compose exec -T celery_worker python manage.py test main_product_manager --keepdb
# Example: single test
docker compose exec -T celery_worker python manage.py test main_product_manager.tests.MyTestCase.test_method --keepdb
```

**Django management inside Docker:**
```bash
docker compose exec web python manage.py <command>
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

**Django root:** `price_manager/` (contains `manage.py`, all apps, `requirements.txt`).

**Settings:** `DJANGO_SETTINGS_MODULE` is **`price_manager.settings.prod`** (set in `manage.py`, `wsgi.py`, `asgi.py`, `celery.py`). Settings is a *package*, not a module — `price_manager/price_manager/settings/`:

- `__init__.py` is empty. Pointing Django at `price_manager.settings` loads **no settings at all**.
- `prod.py` is the entry point: it star-imports `base`, `api`, `project`, `celery`, `databases`, `messages`, `storages`, `third_party`, then concatenates `INSTALLED_APPS` and `MIDDLEWARE`.
- To change a setting, edit the *topic file* that owns it — `base.py` (core Django, `SECRET_KEY`), `databases.py`, `celery.py`, `storages.py` (S3), `third_party.py`, `messages.py`, `api.py` (DRF), `project.py` (`PROJECT_INSTALLED_APPS`, `PROJECT_MIDDLEWARE`, `PIM_TOKEN`/`PIM_HOST`).

## Running more than one agent

Two Claude sessions in one checkout are not two workers — they are one working
tree with two writers. They have to be kept apart on two axes, and only one of
them is the obvious one.

**Files — a worktree per agent, including the first.** The main checkout is not
the privileged tree that gets to keep branching; it is the *shared* one, and a
`git checkout` there re-points every file under whoever else is working mid-edit.
Use `EnterWorktree`, which branches from `origin/main` into
`.claude/worktrees/<name>/`. Run it from the repo root: a worktree belongs at
`<repo>/.claude/worktrees/`, and `EnterWorktree` invoked from the inner
`price_manager/` Django directory nests one a level too deep, which is how
`price_manager/price_manager/.claude/worktrees/lucid-kowalevski-a5c256` got there.
`git worktree list` is the check; `git worktree remove` plus `prune` is the fix.

`.claude/hooks/guard_branch_switch.py` asks before a branch switch or an
unaddressed stash lands in shared state — deliberately making the shared tree the
awkward one to work in. The stash stack is shared across every worktree too, so
create with `git stash push -u -m "<tag>"` and restore with
`git stash apply <sha>` — never a bare `pop`.

**Containers — one agent owns the stack, and a worktree does not divide it.**
`docker-compose.yml` defaults `PROJECT_NAME` to `price_manager`, so every worktree
resolves to the *same* containers, the same `postgres_data` volume and the same
`test_price_manager_db`. A second `docker compose up` recreates the containers
against its own bind mount and silently re-points the first agent's running app;
a migration from the other branch lands in the shared database. Nothing errors —
that is what makes this the worse of the two. Run `docker compose ps` and ask
before starting the stack or the test suite.

A second stack *is* workable: the compose file is parameterized (`PROJECT_NAME`,
`WEB_PORT`, `DB_PORT`, `REDIS_PORT`), and `run-price-manager` and `ui-review`
derive their polling and `BASE_URL` from `WEB_PORT` instead of hardcoding 8000.

It is not automatic, and the trap is that the failure is silent. `.env` is
gitignored, so a fresh worktree has none and every one of those vars falls back
to the shared default — `docker compose up` there drives the main checkout's
containers against your bind mount. Naming a stack is therefore a *per-command*
act (`PROJECT_NAME=… WEB_PORT=… docker compose …`), since shell state does not
survive between tool calls. Serializing stays the safe default; isolate when you
genuinely need two stacks at once, and read "Which stack you are talking to" in
`run-price-manager` first.

`media/` is gitignored on the same principle, and that one costs more because it
looks like a regression. A fresh worktree gets its own empty `media/`, and it
does not inherit the main checkout's mode — inside the container it is 0755
where the shared tree's is 0777, and the worker runs as uid 1011. Every
`supplier_product_manager` test that creates a `SupplierFile` then dies with
`PermissionError: [Errno 13] ... '/app/media/setting_<pk>'`: 16 errors in an
otherwise-green suite, belonging to neither the branch nor the code under test.
Once per worktree:

```bash
docker compose run --rm --no-deps --user root -T celery_worker sh -c 'mkdir -p /app/media && chmod -R 777 /app/media'
```

`chmod` from Git Bash on the host does not change the mode the container sees —
that only works from inside a container. And it has to be `run --no-deps` (so it
does not start the shared `db`/`redis`), not `exec`: `exec` attaches to the
running container, whose `/app` is whichever tree last ran `up`.

## Direction of travel — read this before adding code

There are two product catalogs in the tree. **They are not peers, and the newer one is not the future.**

**The legacy, supplier-centric stack is the live system. Build here.**

- `core` → the UI hub and the shopping-tab/cart feature (see below)
- `supplier_manager` → `Supplier`, `Currency`, `Category` (MPTT), `Manufacturer`, `Discount`
- `supplier_product_manager` → `SupplierProduct` (supplier's raw price row), `Setting`/`Link` (column-mapping config for Excel imports), `SupplierFile` (upload queue)
- `main_product_manager` → `MainProduct` (canonical product record, multiple price fields, full-text `SearchVectorField` with a PostgreSQL GIN index, PIM integration)
- `product_price_manager` → `PriceManager` (markup rules: source price → dest price, with formula), `PriceTag` (per-product-per-rule snapshot), `update_prices()` (bulk apply)
- `file_manager`, `blogapp`, `api_auth`, `pim_api` → supporting

**The API-driven stack is being retired. Do not build new features here.**

- `product`, `pricing`, `supplier`, `supplier_feed`, `dataframe`

The API-first rewrite did not work out. `product` is currently being **recreated as a PIM-linked mirror and reconnected to the legacy stack** — `product/models.py` is now a plain mirror (`pim_id`, `number`, `name`, `categories` as MPTT, `raw_data` JSON), and `product/migrations/0005_seed_products_from_main_product_pim_ids.py` seeds it from `MainProduct.pim_id`. There is no embedding, no characteristics JSONB, and no `ImportJob`/`CharacteristicMutationJob` — earlier revisions of this file described those; they no longer exist.

**Do not delete these apps or their routes without confirming there is no external consumer.** They are wired into `api_urls.py` (`/api/dataframe/`, `/api/supplier-feed/`, `/api/suppliers/`, `/api/pricing/`) behind token auth. Whether anything outside this repo calls them is an **open question** — ask before removing.

Retirement status is otherwise clean: nothing in the legacy apps imports `product`, `pricing`, `supplier`, `supplier_feed`, or `dataframe`. Those five reference only each other and are reachable only via `/api/`.

A `PreToolUse` hook (`.claude/hooks/guard_retiring_stack.py`) turns an edit under `pricing`, `supplier`, `supplier_feed` or `dataframe` into a permission prompt — `supplier` and `supplier_manager` are one keystroke apart and that is the usual way code lands in a dead app. It is a net, not a gate: `product` is excluded on purpose (it is being recreated), and a file rewritten through `Bash` does not pass through it.

## Where the UI lives: `core`

`core` is the largest and most active app, and holds most of the front end:

- **102 of the repo's 146 templates** are under `core/templates/`, including templates owned by other apps' views (`supplier/`, `manufacturer/`, `currency/`, `category/`, `main/`, `upload/`, `registration/`).
- `core/views.py` (~640 lines) owns the **shopping-tab / cart** feature — `ShoppingTab*` (list, detail, delete, export, import + preview/run) and `CartItem*` (detail, quick-add, product select, add, confirm/unconfirm, remove). Templates in `core/templates/shopping_tab/`.
- `core/models.py` → `CartItem`, `ShoppingTab`, `ShoppingTabExport`, `PersistentNotification`, `TaskRunHistory`.
- `core/middleware.py` → `LoginRequiredMiddleware` (global login gate; anonymous requests under `/api/` get 401 JSON instead of a redirect) and `toaster_middleware`.
- `core/utils.py` → shopping-tab spreadsheet reading (pandas) and export helpers.
- `core/viewmixins.py` → `HtmxMixin` is **dead code**; don't use it.

## Shared infrastructure

**`core/task_runner.py` — `execute_locked_task()`**: Every Celery task should go through this. It provides Redis-based distributed locking (via `cache.add`), wraps the runner in `transaction.atomic()`, and writes a `TaskRunHistory` record with duration and updated-count for every run (success, error, or lock-skipped). Pass `atomic=False` to skip only the transaction — the lock and history still apply. That is for runners that make network calls or sleep between their DB writes (the PIM scans in `main_product_manager`), where an open transaction would idle for the whole scan; it requires the runner to be idempotent, since a partial run's writes stay committed.

**Dispatching a subtask from inside a task — use `dispatch_after_commit()`, not `.delay()`.** Because `execute_locked_task()` wraps the runner in `transaction.atomic()`, a bare `.delay()` inside a runner hands the subtask to Redis while the enclosing transaction can still roll back, so the subtask can start against state that never committed. `core/task_runner.py` provides `dispatch_after_commit(task, *args, **kwargs)` (a `transaction.on_commit` wrapper) for this; outside a transaction it dispatches immediately, so it is safe from views too. Two `main_product_manager` call sites needed it, for different reasons: `_queue_pim_population` queued a task that looks products up by a `pim_id` the same transaction had not committed yet (a stale read, so the task silently populated nothing), while the `reindex_pim_ids` fan-out writes nothing itself but could leave already-dispatched batches running after the parent run rolled back and was recorded as failed.

**Celery:** Worker runs as the `celery_worker` container, broker/backend via Redis. Tasks are `@shared_task` in each app's `tasks.py`.

**REST API:** DRF, mounted at `/api/` via `api_urls.py`. Auth via `api_auth` (token-based). Only the retiring apps expose API routes.

**Frontend:** Django templates + HTMX for partial updates, django-tables2 for tables, django-crispy-forms + Bootstrap, django-autocomplete-light for select widgets.

**The Bootstrap version is split — know this before touching a form.** `settings/third_party.py:27-28` sets `CRISPY_TEMPLATE_PACK = 'bootstrap4'` (and pins `CRISPY_ALLOWED_TEMPLATE_PACKS` to the same), while `core/templates/base.html:12,62` loads Bootstrap **5.3.0** from jsdelivr. So the ~30 crispy-rendered templates emit BS4 markup into a BS5 stylesheet.

This is less dramatic than it sounds, and the nuance is the useful part: BS5 dropped `form-group`, `form-row`, `custom-select` and `form-control-file`, but kept `form-control`. Inputs therefore stay styled and most forms look right — the «Новый товар» modal renders 8 dead `.form-group` wrappers alongside 10 live `.form-control`s and looks fine. Visible breakage is confined to the four dropped classes: an unstyled dropdown, a collapsed two-column row, a file input rendered as bare text. **Count them on the screen before blaming this mismatch for a layout bug** — `document.querySelectorAll('.custom-select, .form-row, .form-control-file').length`.

Do not "fix" it by flipping the pack to `bootstrap5`: only `crispy-bootstrap4` is in `requirements.txt` and `INSTALLED_APPS`, so that is a dependency migration with markup churn across 30 templates, not a settings change.

There are **two HTMX response conventions**, both documented as skills under `.claude/skills/`:

- **`htmx-modal-crud`** — list + Bootstrap modal form, success returns `HttpResponseClientRefresh()` (full reload). The default for ordinary CRUD screens.
- **`htmx-oob-fragments`** — one action updates several regions in place via `hx-swap-oob`, no reload. Used throughout `core/templates/shopping_tab/`. Reach for it when a reload would lose state the user cares about (scroll position, an open modal, a filled filter).

## Per-app knowledge keepers

Each significant app has a **keeper agent** and a knowledge file it owns:

| App | Agent | File |
|---|---|---|
| `main_product_manager` | `main-product-keeper` | `.claude/knowledge/main_product_manager.md` |
| `core` | `core-keeper` | `.claude/knowledge/core.md` |
| `product` | `product-keeper` | `.claude/knowledge/product.md` |
| `supplier_product_manager` | `supplier-product-keeper` | `.claude/knowledge/supplier_product_manager.md` |
| `supplier_manager` | `supplier-manager-keeper` | `.claude/knowledge/supplier_manager.md` |
| `product_price_manager` | `price-rules-keeper` | `.claude/knowledge/product_price_manager.md` |
| `pricing` `supplier` `supplier_feed` `dataframe` | `retiring-stack-keeper` | `.claude/knowledge/retiring_stack.md` |

**Consult the keeper before working in its app.** It reads its knowledge file,
verifies the claims against current code, and answers with `file:line` refs.

**Record back afterwards** with `/record-insight <app>` — a `Stop` hook
(`.claude/hooks/suggest_record.py`) nudges when a session touched an app dir.
Without that step the files freeze and rot; recording is what makes the system
worth having.

**The boundary — keep these three from drifting into each other:**

- `CLAUDE.md` / `AGENTS.md` — repo-wide invariants, architecture, direction of
  travel. The source of truth. **Keepers must not restate this.**
- `.claude/knowledge/<app>.md` — app-local mechanism and traps found by working
  in that app: surprising side effects, cache keys that don't cover what you'd
  assume, deliberate convention exceptions. Cross-linked with `[[app_name]]`.
- The user's memory dir — workflow preferences, not code facts.

Apps with no keeper (`file_manager`, `api_auth`, `pim_api`, `blogapp`) are too
small to justify one; anything important about them belongs in this file.

## Conventions

- **UI strings are Russian.** Model `verbose_name`s, `Meta.verbose_name`, form labels, and template copy are all Russian — match that when adding models or screens. Code identifiers and comments are English.
- **Routes are registered centrally** in `price_manager/price_manager/urls.py`, not in per-app `urls.py`. Only `main_product_manager` and `blogapp` are `include()`d.
- **Always commit migrations.** They are tracked normally. (`.gitignore` used to carry a `*/migrations/*.py` line; it was a no-op — it matched only depth-2 paths while migrations sit at depth 3 — and has been removed.)

## Key cross-app dependencies

- `product_price_manager` imports from both `main_product_manager` and `supplier_product_manager` — pricing logic bridges them.
- `main_product_manager.MainProduct._build_searchvector()` calls the external PIM API (via `main_product_manager/utils.py` → `pim_client.site` → the `pim_api` package) to enrich the search vector with PIM category/tag/description data. It is a network call inside a model method.
- **`main_product_manager/pim_client.py` instantiates `SiteAPI(token=settings.PIM_TOKEN, host=settings.PIM_HOST)` at import time**, and `supplier_product_manager/admin.py` imports it transitively. If `PIM_TOKEN`/`PIM_HOST` are unset, the *entire app* fails to boot with a pydantic `ValidationError` — not just PIM features. `docker-compose.yml` supplies placeholder defaults.

## Database

PostgreSQL 17 (`pgvector/pgvector:pg17` image). One full-text index type is in use:

- `GinIndex` on `MainProduct.search_vector` and `supplier_manager.Category.search_vector`, built with `config='russian'`.

There is **no pgvector/HNSW/embedding usage anywhere in the Python code** — semantic search went away with the API rewrite. The image still ships the extension; nothing depends on it.

## Production snapshots — `backups/`

`backups/` holds pg_dump custom-format snapshots of the production database (`pricemanager_YYYYMMDD_HHMMSS.dump`). The dev database is empty, so these are the only real data on the machine: 156k `MainProduct`, 168k `SupplierProduct`, 527k `PriceTag`, 816 categories, 85 supplier column-mapping `Setting`s. **The `prod-snapshot` skill is the way in** — it carries the verified restore procedure and the traps (a bare `manage.py migrate` fails on the snapshot; migrating `supplier_product_manager` deletes every `PriceTag` and zeroes every price field).

Three rules govern their use, and they are not the skill's to relax:

- **Investigation only, never a test dependency.** `backups/` is gitignored and `.github/workflows/ci.yml` runs the suite against an empty pgvector service. A test that needs a snapshot passes locally and fails or silently skips in CI. Turn every finding into a committed fixture before it becomes a test.
- **Never restore over `price_manager_db`.** Always a separate database — `pricemanager_snapshot`. `.claude/hooks/guard_prod_data.py` refuses the obvious ways to break this (`pg_restore -d price_manager_db`, `dropdb`/`DROP DATABASE` on it); it is a net, not a gate.
- **Nothing derived from a snapshot leaves the machine.** No dump-derived values in commits, PR bodies, GitHub issues, or Telegram messages — `.claude/telegram-bot/` posts to a group chat and the `tg-*` skills file public issues. The dump holds `auth_user` (real accounts, emails and password hashes), `core_cartitem` and supplier pricing. Aggregates and row counts only.
