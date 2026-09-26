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

`staticfiles/` is the same trap from another angle. Static storage is whitenoise's
`CompressedManifestStaticFilesStorage`, which needs a collected manifest, and only
the `web` service runs `collectstatic` (in its start command; CI runs it
explicitly). Start just `db`/`redis`/`celery_worker` in a fresh worktree and every
test that renders `base.html` fails with `ValueError: Missing staticfiles manifest
entry for 'js/htmx.min.js'` — 10 errors, none of them yours. Once per worktree:

```bash
docker compose exec -T celery_worker python manage.py collectstatic --noinput
```

## Direction of travel — read this before adding code

There are two product catalogs in the tree. **They are not peers, and the newer one is not the future.**

**The legacy, supplier-centric stack is the live system. Build here.**

- `core` → the UI hub and the shopping-tab/cart feature (see below)
- `supplier_manager` → `Supplier`, `Currency`, `Discount`. Its `Category` and `Manufacturer`/`ManufacturerDict` were retired in the product shift's Phase 2b — categories are `product.Category`, brands `product.Brand`, both from PIM
- `supplier_product_manager` → `SupplierProduct` (supplier's raw price row), `Setting`/`Link` (column-mapping config for Excel imports), `SupplierFile` (upload queue)
- `main_product_manager` → `MainProduct` — since the product shift's Phase 2b, a **per-supplier stock + price row** hanging off `product.Product` (multiple price fields, `stock`, logs, the PIM link push). Its own search vector, description, categories, manufacturer and dimensions are gone; search, name, brand and categories live on `product.Product`
- `product_price_manager` → `PriceManager` (markup rules: source price → dest price, with formula), `PriceTag` (per-product-per-rule snapshot), `update_prices()` (bulk apply). `PriceManager.supplier` may be NULL: such a rule prices **ГП rows without a supplier** (`_fitting_unsupplied_mps`) — only from ГП prices or a fixed price, never from the supplier price list, and never the prime cost of a set row. All rules, of suppliers and without, are listed at «Наценки ГП» (`/price-manager/`); supplier-less ones are created only there.
- **ГП rows without a supplier** (`MainProduct.supplier` NULL): sets, leftover stock, returns, bonuses. Created and fully edited (all prices and stock) in the «Строка ГП» modal (`MainProductForm`), from the toolbar of «Товары» or from the product card (`?product=<pk>`, sku = the product's number). **A ГП row never exists without a Product**: every hand-written path (the modal, the admin and its import) goes through `main_product_manager.utils.ensure_product`/`product_for_sku` (case-insensitive, creates the Product), and the copy-to-main import runs `link_unlinked_main_products(main_product_ids=…)`, which creates missing Products too. Changing a row's sku moves it to the Product of the new sku. Their stock is hand-entered only: `update_stocks` skips rows without a supplier (otherwise it resets every row with no price-list row to 0). **Every set has one set row** (`MainProduct.is_set`, one per Product): no supplier, `prime_cost` = Σ amount × component's main prime cost, written only by `product/services/set_rows.sync_set_rows` and left NULL while any component lacks a cost. It runs at the end of `update_prices` — sets last, after the rules that change component costs — followed by one more pass of supplier-less rules and the set rows' own tags; and after `sync_product_sets`.
- `product_pricing` («Цены товаров», `/product-pricing/`) → the **second pricing level, on `product.Product`**. `Product` carries *base prices* — the seven `MP_PRICES` (ГП) plus the three supplier price-list prices (ПП: `supplier_price`, `rrp`, `supplier_discount_price`, converted to tenge by the row's supplier currency) — consolidated exactly as the export does: top `Supplier.price_priority` level, **on a level the supplier with the lowest prime cost wins and prices come from it**, falling back by cost, then to lower levels. Not a per-field minimum — that would mix prices of different suppliers. Written only by `product/services/prices.recalculate_base_prices`. `ProductPriceType` (UI-defined: «Розничная»…) + `ProductPriceRule` (source base price → type; specific products — set from the product card, priority 10 so it beats the default 100 —, categories with descendants, brands, «только наборы», source-price range, period; markup %, increase, fixed, round-up step; lowest `priority` wins, rules never stack; saving or deleting a rule queues a recalculation; the rule modal has a live preview — `services.preview_rule` — of how many products it takes, from which rules, and example before/after prices) produce `ProductPrice` rows (value + source + rule), shown as columns on `/products/` for types with `show_on_page`. Rules never write `Product` or `MainProduct` prices. `product_pricing.update_product_prices` (beat, same interval as `update-prices`) runs base → rules, then fans out PIM pushes after commit: changed prices go to the product's `PriceManagerProduct` via `upsertAsync`, into fields named by `settings.PIM_PRODUCT_PRICE_FIELDS` (base prices, env JSON) and `ProductPriceType.pim_field` (calculated). Both empty by default — nothing is sent until PIM staff create those fields; `Product.pim_pushed_prices` is the last-sent snapshot.
- `file_manager`, `blogapp`, `api_auth`, `pim_api` → supporting
- `releases` («Обновления», «Что нового» in the navbar) → `Release`: a version, a short `summary` and an article for managers, at `/releases/<version>/`. The article is stored as sanitized HTML (`article_html`, cleaned by `nh3` on every save) and duplicated as `article_markdown`, rebuilt from the HTML on every save (`markdownify`) and served at `/releases/<version>/markdown/` — never edit the Markdown by hand. Saving a release with `is_published=True` and no `notified_at` dispatches `releases.notify_release`, which puts the summary plus a link to the article into every active user's `PersistentNotification` once, then sets `notified_at`. Those notifications are `kind='release'` and are deleted only by the user; the article page is still the durable record. Authoring is in the admin; drafts are visible to staff only.
- `developers` («Разработчикам») → `Feedback`: the navbar feedback modal. Each message is its own Bitrix24 task (`tasks.task.add` via the inbound webhook `BITRIX24_FEEDBACK_WEBHOOK`, responsible `BITRIX24_FEEDBACK_RESPONSIBLE_ID`), sent by `developers.send_feedback` with a lock *per message*; the row stays in the admin whether or not the task got created, with a «resend» action. The webhook is separate from the OAuth login app in `core/bitrix24.py`.

**The API-driven stack is being retired. Do not build new features here.**

- `pricing`, `supplier`, `supplier_feed`, `dataframe`

**`product` is the exception, and it has moved further than the other four.** The API-first rewrite did not work out, and `product` was recreated as a **PIM-linked mirror** reconnected to the legacy stack: `pim_id`, `number` (= `MainProduct.sku`), `name`, `categories` as MPTT, `brand`, `raw_data` JSON, and a local `search_vector`. Since the product-shift Phase 1 it is the **root of search and filtering**, served at `/products/`, with a card at `/products/<pk>/` (prices and the rules behind them, ГП rows, set composition; edit, delete, relink ГП, «наценка на этот товар»). Card edits follow two constraints from the code: a Product with PIM content (`raw_data`) has name/brand/categories read-only, since `apply_pim_product` overwrites them; and ГП rows are only ever *moved* between Products, never merely unlinked, and a Product is deletable only with no ГП rows — `link_unlinked_main_products` re-links an unlinked row nightly to the Product numbered by its sku, recreating it if missing, while it never touches an existing link (hand-created and imported rows are linked at once, see ГП rows without a supplier above); Phase 2b retired the old main page (`/mainproduct/` redirects there) — the design and every decision behind it are in `.claude/shift-to-product-brief.md`. Build there when the work serves that shift; do not grow it into anything independent of PIM and the legacy stack. There is no embedding, no characteristics JSONB, and no `ImportJob`/`CharacteristicMutationJob` — earlier revisions of this file described those; they no longer exist.

**Nothing outside this repo calls them — confirmed by the owner on 2026-09-19.** They are wired into `api_urls.py` (`/api/dataframe/`, `/api/supplier-feed/`, `/api/suppliers/`, `/api/pricing/`) behind session auth, and those routes have no external consumer, so the four apps can be removed. That used to be an open question; it is not any more, so don't ask again.

**Removing them is not just deleting directories — `product`'s migrations depend on them.** `product/migrations/0007_product_pim_id_is_price_manager_product.py` declares `('supplier_feed', '0001_initial')` as a dependency and loads `SupplierFeedEntry`/`SupplierLink` in its `RunPython`, while `supplier_feed.0001` depends on `dataframe.0001`, `pricing.0001`, `product.0001` and `supplier.0001` and holds FKs into `product.Product`. Delete the apps without first cutting that edge — drop the dependency and the two `get_model` calls from `0007`, or squash `product`'s migrations — and every `migrate` fails on a missing parent node, including CI's fresh database. Production has already applied `0007`, so editing it changes nothing there; the edit only has to keep a fresh database migrating.

Retirement status of the other four is clean: nothing in the legacy apps imports `pricing`, `supplier`, `supplier_feed` or `dataframe`; they reference only each other and are reachable only via `/api/`. `product` differs on both counts — `MainProduct.product` is an FK to it, and it is served at `/products/`.

A `PreToolUse` hook (`.claude/hooks/guard_retiring_stack.py`) turns an edit under `pricing`, `supplier`, `supplier_feed` or `dataframe` into a permission prompt — `supplier` and `supplier_manager` are one keystroke apart and that is the usual way code lands in a dead app. It is a net, not a gate: `product` is excluded on purpose (it is where the product shift lives), and a file rewritten through `Bash` does not pass through it.

## Where the UI lives: `core`

`core` is the largest and most active app, and holds most of the front end:

- **81 of the repo's 123 templates** are under `core/templates/`, including templates owned by other apps' views (`supplier/`, `currency/`, `main/`, `upload/`, `registration/`).
- `core/views.py` (~710 lines) owns the **shopping-tab / cart** feature — `ShoppingTab*` (list, detail, delete, export, import + preview/run) and `CartItem*` (detail, quick-add, product select, add, confirm/unconfirm, remove). Templates in `core/templates/shopping_tab/`.
- `core/models.py` → `CartItem`, `ShoppingTab`, `ShoppingTabExport`, `PersistentNotification`, `TaskRunHistory`.
- **`PersistentNotification` has lifetimes by `kind`** — read through `.visible()`. A supplier-import confirmation never expires on its own: anything that moves an `ImportRun` out of `STATUS_NEEDS_CONFIRMATION` must call `supplier_product_manager.tasks.dismiss_confirmations`. Details in `.claude/knowledge/core/models-and-notifications.md`.
- `core/middleware.py` → `LoginRequiredMiddleware` (global login gate; anonymous requests under `/api/` get 401 JSON instead of a redirect) and `toaster_middleware`.
- `core/utils.py` → shopping-tab spreadsheet reading (pandas) and export helpers.
- `core/viewmixins.py` → `HtmxMixin` is **dead code**; don't use it.
- `core/bitrix24.py` + `bitrix24_login`/`bitrix24_callback` in `core/views.py` → **login with Bitrix24** (OAuth of a local Bitrix24 app, hand-rolled on `requests`: `social-core` has no Bitrix24 backend, and Bitrix's flow — code exchanged by GET at `oauth.bitrix.info`, no `redirect_uri` — does not fit a generic one). Off unless `BITRIX24_PORTAL`/`BITRIX24_CLIENT_ID`/`BITRIX24_CLIENT_SECRET` are all set (`settings/third_party.py`). No tokens are stored. **Identity is the Bitrix user ID**, kept in `core.Bitrix24Account` (one-to-one both ways); Bitrix-inactive or non-`employee` users are always refused. An anonymous callback logs in: (1) by linked ID — staff included, e-mail irrelevant; else (2) by e-mail, case-insensitive, auto-linking **only** a non-staff user with no usable password (one Bitrix itself created) — anyone else gets «войдите по паролю» and links afterwards, because an employee can edit their own Bitrix e-mail; else (3) a new user, linked. A logged-in callback is **link mode**: it only ever ties the Bitrix ID to the current user, never switches users, and refuses if either side is already linked elsewhere. `BITRIX24_LINK_REQUIRED` (default `false`) turns on `core.middleware.Bitrix24LinkRequiredMiddleware`, which sends any logged-in, unlinked, non-superuser to `accounts/bitrix24/link/`; the password stays a fallback login. `BITRIX24_AUTO_CREATE_USERS` (default `true`) is the admission policy: while PM is young every employee gets a user on first login, and PM has no roles, so that user can do everything. Expected to narrow — `false` admits only existing PM users. If *every* first-time employee is refused with «не указан e-mail», the app card has scope `user_brief`, which silently drops `EMAIL` from `user.current` (no error) — raise it to `user_basic`. The e-mail-takeover hole remains only for Bitrix-created users not yet linked, and closes on each one's first login after this change.

## Shared infrastructure

**`core/task_runner.py` — `execute_locked_task()`**: Every Celery task should go through this. It provides Redis-based distributed locking (via `cache.add`), wraps the runner in `transaction.atomic()`, and writes a `TaskRunHistory` record with duration and updated-count for every run (success, error, or lock-skipped). Pass `atomic=False` to skip only the transaction — the lock and history still apply. That is for runners that make network calls or sleep between their DB writes (the PIM scans in `main_product_manager`), where an open transaction would idle for the whole scan; it requires the runner to be idempotent, since a partial run's writes stay committed.

**Dispatching a subtask from inside a task — use `dispatch_after_commit()`, not `.delay()`.** Because `execute_locked_task()` wraps the runner in `transaction.atomic()`, a bare `.delay()` inside a runner hands the subtask to Redis while the enclosing transaction can still roll back, so the subtask can start against state that never committed. `core/task_runner.py` provides `dispatch_after_commit(task, *args, **kwargs)` (a `transaction.on_commit` wrapper) for this; outside a transaction it dispatches immediately, so it is safe from views too. The `reindex_pim_ids` fan-out is the standing example (an earlier one, `_queue_pim_population`, went with Phase 2b): it dispatches batches that select the local `product.Product` rows its own transaction just created or numbered — dispatched early, a batch finds none of them, and after a rollback the already-dispatched batches keep running against a parent run recorded as failed.

**Celery:** Worker runs as the `celery_worker` container, broker/backend via Redis. Tasks are `@shared_task` in each app's `tasks.py`.

**REST API:** DRF, mounted at `/api/` via `api_urls.py`. Auth via `api_auth` is session-based — DRF `SessionAuthentication` + `IsAuthenticated` (`settings/api.py`), and `api_auth/views.py` logs in with `django.contrib.auth.login` behind a CSRF cookie. There is no token auth: `rest_framework.authtoken` isn't installed and nothing uses `TokenAuthentication`. Only the retiring apps expose API routes.

**Frontend:** Django templates + HTMX for partial updates, django-tables2 for tables, django-crispy-forms + Bootstrap, django-autocomplete-light for select widgets.

**The Bootstrap version is split — know this before touching a form.** `settings/third_party.py:29-30` sets `CRISPY_TEMPLATE_PACK = 'bootstrap4'` (and pins `CRISPY_ALLOWED_TEMPLATE_PACKS` to the same), while `core/templates/base.html:12,62` loads Bootstrap **5.3.0** from jsdelivr. So the ~30 crispy-rendered templates emit BS4 markup into a BS5 stylesheet.

This is less dramatic than it sounds, and the nuance is the useful part: BS5 dropped `form-group`, `form-row`, `custom-select` and `form-control-file`, but kept `form-control`. Inputs therefore stay styled and most forms look right — the «Новый товар» modal renders 8 dead `.form-group` wrappers alongside 10 live `.form-control`s and looks fine. Visible breakage is confined to the four dropped classes: an unstyled dropdown, a collapsed two-column row, a file input rendered as bare text. **Count them on the screen before blaming this mismatch for a layout bug** — `document.querySelectorAll('.custom-select, .form-row, .form-control-file').length`.

Do not "fix" it by flipping the pack to `bootstrap5`: only `crispy-bootstrap4` is in `requirements.txt` and `INSTALLED_APPS`, so that is a dependency migration with markup churn across 30 templates, not a settings change.

There are **two HTMX response conventions**, both documented as skills under `.claude/skills/`:

- **`htmx-modal-crud`** — list + Bootstrap modal form, success returns `HttpResponseClientRefresh()` (full reload). The default for ordinary CRUD screens.
- **`htmx-oob-fragments`** — one action updates several regions in place via `hx-swap-oob`, no reload. Used throughout `core/templates/shopping_tab/`. Reach for it when a reload would lose state the user cares about (scroll position, an open modal, a filled filter).

## Per-app knowledge keepers

Each significant app has a **keeper agent** and a knowledge directory it owns —
one markdown file per topic:

| App | Agent | Directory |
|---|---|---|
| `main_product_manager` | `main-product-keeper` | `.claude/knowledge/main_product_manager/` |
| `core` | `core-keeper` | `.claude/knowledge/core/` |
| `product` | `product-keeper` | `.claude/knowledge/product/` |
| `supplier_product_manager` | `supplier-product-keeper` | `.claude/knowledge/supplier_product_manager/` |
| `supplier_manager` | `supplier-manager-keeper` | `.claude/knowledge/supplier_manager/` |
| `product_price_manager` | `price-rules-keeper` | `.claude/knowledge/product_price_manager/` |
| `pricing` `supplier` `supplier_feed` `dataframe` | `retiring-stack-keeper` | `.claude/knowledge/retiring_stack/` |

**Consult the keeper before working in its app.** It reads its directory's
index and the topics the question touches, verifies the claims against current
code, and answers with `file:line` refs.

**Layout.** Every topic starts with front matter — `title`, `summary`, `code`
(the repo paths it covers). `.claude/knowledge/README.md` and each
`<app>/README.md` are **generated** from that front matter by
`.claude/tools/knowledge_index.py`; never edit them by hand. CI runs it with
`--check`, which fails on a stale index, a topic without front matter, a
flat `.claude/knowledge/<app>.md`, or a `[[app/topic]]` link that points
nowhere. `.claude/knowledge/glossary.md` is hand-written: Russian UI terms
(«ГП», «Набор», «уровень по цене») mapped to models, fields and PIM entities.

**Record back afterwards** with `/record-insight <app>` — a `Stop` hook
(`.claude/hooks/suggest_record.py`) nudges when a session touched an app dir.
The keeper picks or starts the topic; keepers have no shell, so the caller
regenerates the index afterwards (the skill says how). Without that step the
topics freeze and rot; recording is what makes the system worth having.

**The boundary — keep these three from drifting into each other:**

- `CLAUDE.md` / `AGENTS.md` — repo-wide invariants, architecture, direction of
  travel. The source of truth. **Keepers must not restate this.**
- `.claude/knowledge/<app>/<topic>.md` — app-local mechanism and traps found by
  working in that app: surprising side effects, cache keys that don't cover what
  you'd assume, deliberate convention exceptions. Cross-linked with `[[app]]`
  (the directory) and `[[app/topic]]`.
- The user's memory dir — workflow preferences, not code facts.

Apps with no keeper (`file_manager`, `api_auth`, `pim_api`, `blogapp`) are too
small to justify one; anything important about them belongs in this file.

**The PIM itself has a consultant, not a keeper.** `pim-docs` answers what
AtroCore/AtroPIM *documents* and what *our instance's* schema says: it reads
help.atrocore.com as markdown from the public GitHub mirror, pinned to
`DOCS_REF` in `.claude/tools/pim_docs.py`, and makes read-only GETs of the
instance's `/api/metadata` and `/openapi.json`. It keeps no knowledge directory.
What we learn about *our* integration still goes to `main-product-keeper` /
`product-keeper`. **When the PIM is upgraded, bump `DOCS_REF`.**
`pim_docs.py instance version` reports a mismatch.

## Conventions

- **UI strings are Russian.** Model `verbose_name`s, `Meta.verbose_name`, form labels, and template copy are all Russian — match that when adding models or screens. Code identifiers and comments are English.
- **Routes are registered centrally** in `price_manager/price_manager/urls.py`, not in per-app `urls.py`. Only `main_product_manager`, `blogapp` and `api_urls` (the retiring stack's `/api/` mount) are `include()`d — `api_urls` currently appears twice in that file, which looks like an uncleaned duplicate rather than a deliberate double-mount.
- **Always commit migrations.** They are tracked normally. (`.gitignore` used to carry a `*/migrations/*.py` line; it was a no-op — it matched only depth-2 paths while migrations sit at depth 3 — and has been removed.)

## Key cross-app dependencies

- `product_price_manager` imports from both `main_product_manager` and `supplier_product_manager` — pricing logic bridges them.
- Nothing on the `MainProduct` save path calls PIM any more — `_build_searchvector()` and its network call went with the search vector in Phase 2b. PIM is reached from `main_product_manager/utils.py` (card views' `get_pim_data`, the photo proxy `fetch_pim_image`, `push_pim_links`) and from `product/services/pim_sync.py`.
- **`main_product_manager/pim_client.py` instantiates `SiteAPI(token=settings.PIM_TOKEN, host=settings.PIM_HOST)` at import time**, and the root URLconf reaches it transitively — `supplier_product_manager/views.py` (imported by `price_manager/urls.py`) imports `.tasks`, which imports `main_product_manager.utils`, which imports `.pim_client` (`supplier_product_manager/admin.py` does **not** reach it — it only imports `.models`/`.functions`). If `PIM_TOKEN`/`PIM_HOST` are unset, the *entire app* fails to boot with a pydantic `ValidationError` — not just PIM features. `docker-compose.yml` supplies placeholder defaults.

## Database

PostgreSQL 17 (`pgvector/pgvector:pg17` image). One full-text index type is in use:

- `GinIndex` on `product.Product.search_vector`, built with `config='russian'`. (There used to be two more, on `MainProduct` and `supplier_manager.Category`; both went with Phase 2b.) Rank against a stored vector with `SearchRank(F('search_vector'), …)`, never the string `'search_vector'` — the string makes Django re-tokenize the stored vector on every row, with the default config and without the index.

There is **no pgvector/HNSW/embedding usage anywhere in the Python code** — semantic search went away with the API rewrite. The image still ships the extension; nothing depends on it.

## Production snapshots — `backups/`

`backups/` holds pg_dump custom-format snapshots of the production database (`pricemanager_YYYYMMDD_HHMMSS.dump`). The dev database is empty, so these are the only real data on the machine: 156k `MainProduct`, 168k `SupplierProduct`, 527k `PriceTag`, 816 categories, 85 supplier column-mapping `Setting`s. **The `prod-snapshot` skill is the way in** — it carries the verified restore procedure and the traps (a bare `manage.py migrate` fails on the snapshot; migrating `supplier_product_manager` deletes every `PriceTag` and zeroes every price field).

Three rules govern their use, and they are not the skill's to relax:

- **Investigation only, never a test dependency.** `backups/` is gitignored and `.github/workflows/ci.yml` runs the suite against an empty pgvector service. A test that needs a snapshot passes locally and fails or silently skips in CI. Turn every finding into a committed fixture before it becomes a test.
- **Never restore over `price_manager_db`.** Always a separate database — `pricemanager_snapshot`. `.claude/hooks/guard_prod_data.py` refuses the obvious ways to break this (`pg_restore -d price_manager_db`, `dropdb`/`DROP DATABASE` on it); it is a net, not a gate.
- **Nothing derived from a snapshot leaves the machine.** No dump-derived values in commits, PR bodies, GitHub issues, or Telegram messages — `.claude/telegram-bot/` posts to a group chat and the `tg-*` skills file public issues. The dump holds `auth_user` (real accounts, emails and password hashes), `core_cartitem` and supplier pricing. Aggregates and row counts only.
