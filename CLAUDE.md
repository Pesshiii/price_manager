# CLAUDE.md

Guidance for Claude Code in this repository. This file holds repo-wide
invariants; how each app works inside lives in `.claude/knowledge/<app>/` (see
*Per-app knowledge keepers*).

## Commands

```bash
docker compose up --build    # app at http://localhost:8000 (or $WEB_PORT); everything requires login
```

**Tests — the local venv is broken, always use Docker:**
```bash
docker compose exec -T celery_worker python manage.py test <app_label> --keepdb
docker compose exec -T celery_worker python manage.py test main_product_manager.tests.MyTestCase.test_method --keepdb
```

**Management:** `docker compose exec web python manage.py <command>` (`makemigrations`, `migrate`, …).

**Django root:** `price_manager/` (`manage.py`, all apps, `requirements.txt`).

**Settings:** `DJANGO_SETTINGS_MODULE` is **`price_manager.settings.prod`** (set
in `manage.py`, `wsgi.py`, `asgi.py`, `celery.py`). `price_manager/price_manager/settings/`
is a *package* with an empty `__init__.py`, so pointing Django at
`price_manager.settings` loads **no settings at all**. `prod.py` star-imports the
topic files and concatenates `INSTALLED_APPS`/`MIDDLEWARE`. To change a setting,
edit the file that owns it: `base.py` (core Django, `SECRET_KEY`),
`databases.py`, `celery.py` (beat schedule), `storages.py` (S3, static),
`third_party.py` (crispy, Bitrix24), `messages.py` (login exemptions), `api.py`
(DRF), `project.py` (`PROJECT_INSTALLED_APPS`, `PROJECT_MIDDLEWARE`,
`PIM_TOKEN`/`PIM_HOST`).

## Running more than one agent

Two sessions in one checkout are one working tree with two writers. Keep them
apart on two axes.

**Files — a worktree per agent, including the first.** The main checkout is the
*shared* tree: a `git checkout` there re-points every file under whoever is
mid-edit. Use `EnterWorktree` (branches from `origin/main` into
`.claude/worktrees/<name>/`) **from the repo root**, because run from the inner
`price_manager/` it nests the worktree a level too deep. Check with
`git worktree list`, fix with `git worktree remove` + `prune`.
`.claude/hooks/guard_branch_switch.py` asks before a branch switch or an
unaddressed stash lands in shared state. All worktrees share one stash stack:
`git stash push -u -m "<tag>"`, restore with `git stash apply <sha>`, never a bare
`pop`.

**Containers — one agent owns the stack, and a worktree does not divide it.**
`docker-compose.yml` defaults `PROJECT_NAME` to `price_manager`, so every
worktree resolves to the same containers, the same `postgres_data` volume and the
same `test_price_manager_db`. A second `docker compose up` silently re-points the
first agent's app at its own bind mount, and the other branch's migrations land
in the shared database. Nothing errors. Run `docker compose ps` and ask before
starting the stack or the test suite. A second stack is possible (`PROJECT_NAME`,
`WEB_PORT`, `DB_PORT`, `REDIS_PORT`), but `.env` is gitignored, so a fresh
worktree falls back to the shared defaults unless *every command* names its
stack. Serializing is the safe default; read "Which stack you are talking to" in
the `run-price-manager` skill before isolating.

**Once per fresh worktree**, or tests fail for reasons that are not yours:

- `media/` is gitignored, and a new worktree's is 0755 inside the container while
  the worker runs as uid 1011. Every `supplier_product_manager` test that creates
  a `SupplierFile` then dies with `PermissionError … '/app/media/setting_<pk>'`.
  Fix it from inside a container (a host `chmod` does not reach it), and with
  `run --no-deps`, not `exec`, because `exec` attaches to whichever tree last ran `up`:
  ```bash
  docker compose run --rm --no-deps --user root -T celery_worker sh -c 'mkdir -p /app/media && chmod -R 777 /app/media'
  ```
- `staticfiles/`: static storage is whitenoise's `CompressedManifestStaticFilesStorage`,
  and only `web` runs `collectstatic` (CI runs it explicitly). Without it, every
  test that renders `base.html` fails with `Missing staticfiles manifest entry for 'js/htmx.min.js'`:
  ```bash
  docker compose exec -T celery_worker python manage.py collectstatic --noinput
  ```

## Direction of travel — read this before adding code

There are two product catalogs in the tree. **They are not peers, and the newer
one is not the future.**

**The legacy, supplier-centric stack is the live system. Build here.**

- `core` — the UI hub, the shopping tab and cart, the task runner, auth (see below).
- `supplier_manager` — `Supplier`, `Currency`, `Discount`. Categories and brands
  are `product.Category`/`product.Brand` from PIM since Phase 2b. **«Свой склад»**
  is a real `Supplier` (`is_own_stock=True`) for leftover stock, returns and bonuses.
- `supplier_product_manager` — `SupplierProduct` (a supplier's raw price row),
  `Setting`/`Link` (Excel column mapping), `SupplierFile` (upload queue), `ImportRun`.
- `main_product_manager` — `MainProduct` («ГП»): a **per-supplier stock + price
  row** hanging off `product.Product`, with its logs and the PIM link push. Name,
  brand, categories and search live on `product.Product`.
- `product_price_manager` — `PriceManager` («менеджер цен», a markup rule: source
  price → dest price), `PriceTag` («наценка», per-row snapshot), `update_prices()`.
- Supporting: `releases`, `developers` (below), `file_manager`, `blogapp`, `api_auth`, `pim_api`.

Invariants that cross these apps (the mechanics are in the keepers' topics):

- **A ГП row never exists without a Product.** Every write path (the «Строка ГП»
  modal, the admin and its import) goes through `main_product_manager.utils.ensure_product`/`product_for_sku`
  (case-insensitive, creates the Product). The copy-to-main import runs
  `link_unlinked_main_products(main_product_ids=…)`. Changing a row's sku moves it
  to the new sku's Product.
- **A ГП row with `supplier` NULL is a set row** (`MainProduct.is_set`, one per
  set). A stray non-set one, such as an admin import with an empty supplier, is
  moved to «Свой склад» by the next `sync_set_rows`. Only `product/services/set_rows` writes its `prime_cost`, `stock` and
  delivery days. Read any row's delivery days through `MainProduct.get_delivery_days()`.
  A `PriceManager` without a supplier («Наборы») prices only these rows.
- **A hand-made ГП row has no `SupplierProduct`, for any supplier.** `update_stocks`
  skips it, so typed stock stays. Deleting a `SupplierProduct` zeroes its row's
  stock (`post_delete` signal). A rule that computes from a supplier price never
  matches such a row.

**The API-driven stack is being retired. Do not build new features here.**
`pricing`, `supplier`, `supplier_feed`, `dataframe`. No live app imports them,
and they are reachable only under `/api/` and in the Django admin, where each
registers its models. Apart from each other they touch only
`product`: `supplier_feed` imports it and holds FKs into `product.Product`. **Nothing outside this repo calls
them, as the owner confirmed on 2026-09-19 (don't ask again)**, so they can be
removed. **Deleting the directories is not enough:**
`product/migrations/0007_product_pim_id_is_price_manager_product.py` depends on
`('supplier_feed', '0001_initial')` and loads two of its models in `RunPython`,
while `supplier_feed.0001` depends on `dataframe`, `pricing`, `supplier` and
`product.0001`. Cut that edge first (drop
the dependency and the two `get_model` calls, or squash `product`'s migrations),
or every `migrate` fails, including on CI's fresh database. Production has
already applied `0007`, so the edit only has to keep a fresh database migrating.
`.claude/hooks/guard_retiring_stack.py` turns edits under the four into a
permission prompt (`supplier` and `supplier_manager` are one keystroke apart). It
is a net, not a gate: `Bash` rewrites bypass it.

**`product` is the exception.** The API-first rewrite did not work out, and
`product` was recreated as a **PIM-linked mirror** reconnected to the legacy
stack: `pim_id`, `number` (= `MainProduct.sku`), `name`, MPTT `categories`,
`brand`, `raw_data`, a local `search_vector`. It is the **root of search and
filtering**: `/products/` and the card at `/products/<pk>/` (`/mainproduct/`
redirects there). The design and its decisions are in
`.claude/shift-to-product-brief.md`. Build there when the work serves that shift,
but do not grow it into anything independent of PIM and the legacy stack.
`MainProduct.product` is an FK to it. It has no embeddings, no characteristics
JSONB and no `ImportJob`/`CharacteristicMutationJob`; docs that say otherwise are stale.

**Supporting apps without a keeper:**

- `releases` («Обновления», «Что нового» in the navbar). A `Release` has a
  version, a short `summary` and an article at `/releases/<version>/`.
  `article_html` is sanitized by `nh3` on every save. `article_markdown` is
  rebuilt from it (`markdownify`) and served at `/releases/<version>/markdown/`;
  never edit it by hand. Saving with `is_published=True` and no `notified_at`
  dispatches `releases.notify_release`, which sends one `PersistentNotification`
  (`kind='release'`, deleted only by the user) per active user, then sets
  `notified_at`. Releases are authored in the admin, and drafts are staff-only.
- `developers` («Разработчикам»). `Feedback` comes from the navbar modal, and each
  message becomes its own Bitrix24 task (`tasks.task.add` via the inbound webhook
  `BITRIX24_FEEDBACK_WEBHOOK`, responsible `BITRIX24_FEEDBACK_RESPONSIBLE_ID`).
  `developers.send_feedback` sends it with a lock *per message*. The row stays in
  the admin whether or not the task was created, with a «resend» action. This
  webhook is separate from the login app in `core/bitrix24.py`.

## Where the UI lives: `core`

Over half of the repo's templates are under `core/templates/`, including ones
rendered by other apps' views (`supplier/`, `currency/`, `main/`, `upload/`,
`registration/`). Look there for a template you cannot find. `core` owns:

- the **shopping tab / cart**: `ShoppingTab*` and `CartItem*` views in
  `core/views.py`, templates in `core/templates/shopping_tab/`, spreadsheet
  helpers in `core/utils.py`;
- `LoginRequiredMiddleware` (the global login gate; anonymous `/api/` requests get
  401 JSON, not a redirect) and `toaster_middleware`;
- `PersistentNotification`, whose lifetime depends on its `kind`
  (`.claude/knowledge/core/models-and-notifications.md`); read it through
  `.visible()`. A supplier-import confirmation never expires on its own, so
  anything that moves an `ImportRun` out of `STATUS_NEEDS_CONFIRMATION` must call
  `supplier_product_manager.tasks.dismiss_confirmations`;
- **login with Bitrix24** (`core/bitrix24.py`), hand-rolled OAuth that is off
  unless `BITRIX24_PORTAL`/`BITRIX24_CLIENT_ID`/`BITRIX24_CLIENT_SECRET` are all
  set. Identity is the Bitrix user ID. `BITRIX24_AUTO_CREATE_USERS` (default
  `true`) admits every employee on first login, and PM has no roles. The full
  policy and its traps are in `.claude/knowledge/core/bitrix24-login.md`.

`core/viewmixins.py` → `HtmxMixin` is dead code; don't use it.

## Shared infrastructure

**Every new Celery task should go through `core/task_runner.py: execute_locked_task()`**
(a few older `supplier_product_manager` tasks still run inline, a known
exception — see its `tasks-and-imports` topic). It takes a Redis lock (`cache.add`), runs the runner inside `transaction.atomic()`,
and writes a `TaskRunHistory` row for every run (success, error or
lock-skipped). `atomic=False` drops only the transaction. Use it for runners
that make network calls or sleep between their writes, so no transaction idles
across them; such a runner must be idempotent. The worker is the `celery_worker`
container with Redis as broker, and tasks are `@shared_task` in each app's `tasks.py`.

**Dispatching a subtask from inside a task: use `dispatch_after_commit(task, *args, **kwargs)`,
not `.delay()`.** A bare `.delay()` inside the runner's transaction can start the
subtask against state that never commits. Outside a transaction it dispatches
immediately, so it is safe from views too. The why and the `reindex_pim_ids`
example are in `.claude/knowledge/core/task-runner.md`.

**REST API:** DRF at `/api/` (`api_urls.py`), session auth only
(`SessionAuthentication` + `IsAuthenticated`, `settings/api.py`). `api_auth` logs
in with `django.contrib.auth.login` behind a CSRF cookie. There is no token auth.
Apart from `api_auth`, only the retiring apps expose routes.

## Frontend

Django templates + HTMX for partial updates, django-tables2, django-crispy-forms
+ Bootstrap, django-autocomplete-light.

**The Bootstrap version is split.** `settings/third_party.py` sets
`CRISPY_TEMPLATE_PACK = 'bootstrap4'`, while `core/templates/base.html` loads
Bootstrap **5.3.0**, so crispy forms emit BS4 markup into a BS5 stylesheet. BS5
kept `form-control`, so most forms look right, and dead `form-group` wrappers are
harmless. Visible breakage comes only from `custom-select` (an unstyled
dropdown), `form-row` (a collapsed two-column row) and `form-control-file` (a file
input rendered as bare text). Count them on the screen before blaming this for a
layout bug: `document.querySelectorAll('.custom-select, .form-row, .form-control-file').length`.
Do not "fix" it by flipping the pack to `bootstrap5`: only `crispy-bootstrap4` is
installed, so that is a dependency migration with markup churn across every
crispy template, not a settings change.

There are **two HTMX response conventions**, each a skill under `.claude/skills/`:

- **`htmx-modal-crud`**: a list plus a Bootstrap modal form, where success
  returns `HttpResponseClientRefresh()` (a full reload). The default for ordinary CRUD.
- **`htmx-oob-fragments`**: one action updates several regions via `hx-swap-oob`
  with no reload, as in `core/templates/shopping_tab/`. Use it when a reload
  would lose scroll position, an open modal or a filled filter.

## Per-app knowledge keepers

Each significant app has a **keeper agent** that owns a knowledge directory, one
markdown file per topic:

| App | Agent | Directory |
|---|---|---|
| `main_product_manager` | `main-product-keeper` | `.claude/knowledge/main_product_manager/` |
| `core` | `core-keeper` | `.claude/knowledge/core/` |
| `product` | `product-keeper` | `.claude/knowledge/product/` |
| `supplier_product_manager` | `supplier-product-keeper` | `.claude/knowledge/supplier_product_manager/` |
| `supplier_manager` | `supplier-manager-keeper` | `.claude/knowledge/supplier_manager/` |
| `product_price_manager` | `price-rules-keeper` | `.claude/knowledge/product_price_manager/` |
| `pricing` `supplier` `supplier_feed` `dataframe` | `retiring-stack-keeper` | `.claude/knowledge/retiring_stack/` |

**Consult the keeper before working in its app.** It reads its index and the
relevant topics, verifies them against current code, and answers with
`file:line` refs. **Record back afterwards** with `/record-insight <app>` (the
`Stop` hook `.claude/hooks/suggest_record.py` nudges). Keepers have no shell, so
the caller regenerates the index. Without that step the topics freeze and rot.

**Layout.** Every topic opens with front matter (`title`, `summary`, `code`).
`.claude/knowledge/README.md` and each `<app>/README.md` are **generated** from
it by `.claude/tools/knowledge_index.py`; never edit them by hand. CI runs it
with `--check`, which fails on a stale index, a topic without front matter, a flat
`.claude/knowledge/<app>.md`, or a `[[app/topic]]` link that points nowhere.
`.claude/knowledge/glossary.md` is hand-written: Russian UI terms («ГП», «Набор»,
«уровень по цене») mapped to models, fields and PIM entities.

**The boundary.** Keep these three from drifting into each other:
- `CLAUDE.md` / `AGENTS.md` hold repo-wide invariants, architecture and the
  direction of travel. They are the source of truth, and keepers must not restate them.
- `.claude/knowledge/<app>/<topic>.md` holds app-local mechanism and traps.
- The user's memory dir holds workflow preferences, not code facts.

Apps with no keeper (`file_manager`, `api_auth`, `pim_api`, `blogapp`,
`releases`, `developers`) are too small for one; what matters about them goes in
this file.

**The PIM has a consultant, not a keeper.** `pim-docs` answers what
AtroCore/AtroPIM *documents* and what *our instance's* schema says. It reads
help.atrocore.com from its GitHub mirror, pinned to `DOCS_REF` in
`.claude/tools/pim_docs.py`, and makes read-only GETs of the instance's
`/api/metadata` and `/openapi.json`. It keeps no knowledge directory; lessons
about our integration go to `main-product-keeper`/`product-keeper`. **When the
PIM is upgraded, bump `DOCS_REF`**; `pim_docs.py instance version` reports a mismatch.

## Conventions

- **UI strings are Russian**: model and `Meta` `verbose_name`s, form labels and
  template copy. Code identifiers and comments are English.
- **Routes are registered centrally** in `price_manager/price_manager/urls.py`.
  Only `main_product_manager`, `blogapp` and `api_urls` are `include()`d.
  `api_urls` appears twice, which looks like an uncleaned duplicate.
- **Always commit migrations.**

## Key cross-app dependencies

- `product_price_manager` imports from both `main_product_manager` and
  `supplier_product_manager`; the pricing logic bridges them. Those two import
  each other too.
- **`main_product_manager/pim_client.py` and `product/pim_client.py` instantiate
  `SiteAPI(token=settings.PIM_TOKEN, host=settings.PIM_HOST)` at import time**,
  and the root URLconf reaches both through ordinary views. If
  `PIM_TOKEN`/`PIM_HOST` are unset, the *entire app* fails to boot with a
  pydantic `ValidationError`, not just the PIM features. `docker-compose.yml`
  supplies placeholder defaults.
- PIM is called from `main_product_manager/utils.py` (card data, the photo
  proxy, `push_pim_links`), from `product` (`services/pim_sync.py`,
  `services/sets.py`, `pim_content.py`, `satu_export.py`) and from a few
  management commands (`check_pim`, `probe_pim_category_size`). Nothing on the
  `MainProduct` save path calls it.

## Database

PostgreSQL 17 on the `pgvector/pgvector:pg17` image. The extension ships but
nothing uses it: there is no pgvector, HNSW or embedding code. There is one
full-text index, a `GinIndex` on `product.Product.search_vector`, whose vector is
built with `config='russian'`. Rank against it with `SearchRank(F('search_vector'), …)`,
never the string `'search_vector'`. The string makes Django re-tokenize the stored
vector on every row, with the default config and without the index.

## Production snapshots — `backups/`

`backups/` holds pg_dump custom-format snapshots of the production database
(`pricemanager_YYYYMMDD_HHMMSS.dump`). The dev database is empty, so these are
the only real data on the machine. **The `prod-snapshot` skill is the way in.**
It carries the verified restore procedure and the traps: a bare `migrate` fails
on the snapshot, and migrating `supplier_product_manager` deletes every
`PriceTag` and zeroes every price field. Three rules govern their use, and they
are not the skill's to relax:

- **Investigation only, never a test dependency.** `backups/` is gitignored and
  CI runs against an empty database, so a test that needs a snapshot passes
  locally and fails or skips in CI. Turn every finding into a committed fixture first.
- **Never restore over `price_manager_db`.** Always use a separate database,
  `pricemanager_snapshot`. `.claude/hooks/guard_prod_data.py` refuses the obvious
  ways to break this; it is a net, not a gate.
- **Nothing derived from a snapshot leaves the machine.** No dump-derived values
  go in commits, PR bodies, GitHub issues or Telegram messages
  (`.claude/telegram-bot/` posts to a group chat, and the `tg-*` skills file
  public issues). The dump holds real accounts (emails, password hashes), carts
  and supplier pricing. Share aggregates and row counts only.
