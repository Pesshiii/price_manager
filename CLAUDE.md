# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Start everything:**
```bash
docker compose up --build
```
App runs at `http://localhost:8000`. Everything behind `/` requires login (see `core.middleware.LoginRequiredMiddleware`).

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

## Where the UI lives: `core`

`core` is the largest and most active app, and holds most of the front end:

- **102 of the repo's 146 templates** are under `core/templates/`, including templates owned by other apps' views (`supplier/`, `manufacturer/`, `currency/`, `category/`, `main/`, `upload/`, `registration/`).
- `core/views.py` (~640 lines) owns the **shopping-tab / cart** feature — `ShoppingTab*` (list, detail, delete, export, import + preview/run) and `CartItem*` (detail, quick-add, product select, add, confirm/unconfirm, remove). Templates in `core/templates/shopping_tab/`.
- `core/models.py` → `CartItem`, `ShoppingTab`, `ShoppingTabExport`, `PersistentNotification`, `TaskRunHistory`.
- `core/middleware.py` → `LoginRequiredMiddleware` (global login gate, with HTMX-aware redirects) and `toaster_middleware`.
- `core/utils.py` → shopping-tab spreadsheet reading (pandas) and export helpers.
- `core/viewmixins.py` → `HtmxMixin` is **dead code**; don't use it.

## Shared infrastructure

**`core/task_runner.py` — `execute_locked_task()`**: Every Celery task should go through this. It provides Redis-based distributed locking (via `cache.add`), wraps the runner in `transaction.atomic()`, and writes a `TaskRunHistory` record with duration and updated-count for every run (success, error, or lock-skipped).

**Celery:** Worker runs as the `celery_worker` container, broker/backend via Redis. Tasks are `@shared_task` in each app's `tasks.py`.

**REST API:** DRF, mounted at `/api/` via `api_urls.py`. Auth via `api_auth` (token-based). Only the retiring apps expose API routes.

**Frontend:** Django templates + HTMX for partial updates, django-tables2 for tables, django-crispy-forms + Bootstrap (`CRISPY_TEMPLATE_PACK = 'bootstrap4'`), django-autocomplete-light for select widgets.

There are **two HTMX response conventions**, both documented as skills under `.claude/skills/`:

- **`htmx-modal-crud`** — list + Bootstrap modal form, success returns `HttpResponseClientRefresh()` (full reload). The default for ordinary CRUD screens.
- **`htmx-oob-fragments`** — one action updates several regions in place via `hx-swap-oob`, no reload. Used throughout `core/templates/shopping_tab/`. Reach for it when a reload would lose state the user cares about (scroll position, an open modal, a filled filter).

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
