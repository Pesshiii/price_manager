# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Price Manager** is a Django web application for managing product prices, stock levels, and supplier information. It integrates supplier product catalogs, calculates dynamic pricing rules, and maintains a centralized product database with price history tracking.

## Technology Stack

- **Framework**: Django 5.2, PostgreSQL 17
- **Task Queue**: Celery 5.6 with Redis 7 as broker/backend
- **Frontend**: Bootstrap 4, HTMX, django-crispy-forms (crispy-bootstrap4)
- **REST API**: Django REST Framework 3.16, django-cors-headers (session-auth JSON API for SPA frontend at `../price-manager-frontend/`)
- **Data Processing**: Pandas, openpyxl, python-calamine
- **Search**: PostgreSQL full-text search with GIN indexes on SearchVector
- **Storage**: Optional AWS S3-compatible storage (configured via env vars)
- **Deployment**: Docker Compose, Gunicorn, WhiteNoise

## Development Commands

### Local Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Celery Worker (separate terminal)
```bash
celery -A price_manager worker -l info
```

### Docker
```bash
docker compose up --build
```

### Tests
```bash
python manage.py test                              # all tests
python manage.py test core                         # single app
python manage.py test core.tests.MyTestClass       # single class
python manage.py test product.tests.test_import    # single module (new layout)
```
Test layout is mixed: most apps use a single `tests.py`; the `product` app uses a `tests/` package (`test_api_crud.py`, `test_api_filters.py`, `test_import.py`, `test_models.py`).

### Migrations
```bash
python manage.py makemigrations app_name
python manage.py migrate
```

## Architecture

### Product Hierarchy
Three-level structure:
1. **SupplierProduct** — raw products from uploaded supplier files (XLS/XLSX/CSV)
2. **MainProduct** — unified master catalog merging SupplierProducts across suppliers
3. **PriceManager** + **MainProductPrice** — price rules applied to MainProducts

### Product app (in progress)
The `product` app (active on the `Spreadsheetimport` branch) is the eventual replacement for `main_product_manager`. New model: `Product` with JSONB `characteristics`, MPTT `Category` (auto-slug, descendants resolved on list queries), `Brand`, and `CharacteristicType` (M2M to Category, with `value_type`/`required`). Imports go through `product/importer.py`, which consumes pipelines defined in the `dataframe` app. Faceted filtering uses `product/filters.py:_coerce_filter_value` to match int/float/bool/string values against the JSONB column.

### Price Calculation
`PriceManager` rules define: source price field → filters (date range, discount group, category) → `dest_price = source_price * (1 + markup/100) + increase`. Results are pre-calculated into `MainProductPrice` records by Celery tasks.

### File Processing Pipeline
Upload → `setting_upload()` parses file using `Setting` column mappings → creates/updates `SupplierProduct` records → `copy_to_main()` merges into `MainProduct` → Celery tasks propagate prices/stock downstream.

This legacy flow coexists with the new `product` + `dataframe` import path; the two pipelines are not yet unified.

### Dataframe pipeline infrastructure
- Upload sessions write the source file to a temp location and persist metadata (filename, size, uploaded_at) alongside it (`dataframe/sessions.py:session_metadata`).
- Reader-stage output is cached in Redis (`dataframe/cache.py`): cache key = `session_id` + SHA1 of reader cfg, ~1h TTL, 50MB size guard. Backend errors soft-fail (cache miss is acceptable, never blocks the request).
- `delete_session()` invalidates all cache entries for the session via `cache.delete_pattern` (only available on `django_redis`; LocMemCache is a no-op).

### Celery Task Orchestration
All tasks use `execute_locked_task()` (in `core/task_runner.py`) with Redis distributed locking to prevent concurrent execution. Periodic tasks:
- `update_prices_task()` — recalculates MainProductPrice from PriceManager rules
- `update_stocks_task()` — syncs stock from SupplierProduct to MainProduct
- `update_logs_task()` — writes price history to MainProductLog
- `rebuild_categories_task()` — rebuilds MPPT category tree

### REST API Layer
A JSON API is mounted at `/api/` (router: `price_manager/api_urls.py`) for a decoupled SPA frontend.
- `api_auth` app — session-based auth endpoints: `GET /api/auth/csrf/`, `POST /api/auth/login/`, `POST /api/auth/logout/`, `GET /api/auth/me/`
- `dataframe/api/` — registry (`GET /api/dataframe/registry/`), pipeline CRUD (`/api/dataframe/pipelines/`), upload sessions (`POST /api/dataframe/sessions/`, `GET /api/dataframe/sessions/<sid>/` for filename/size/uploaded_at metadata), preview (`POST /api/dataframe/preview/`). Preview accepts an `offset` body field and returns `{offset, has_more, ...}` for infinite-scroll pagination.
- `product/api/` — Product library: `/api/products/products/` (with `GET /api/products/products/facets/` returning aggregated characteristic value counts), `/api/products/categories/`, `/api/products/brands/`, `/api/products/characteristic-types/`. Faceted JSONB filter via `?char__<type_name>=<value>` (repeat the param for OR). Dataframe-driven import at `/api/products/import/{preview,commit}/`; row validation and SKU upsert live in `product/importer.py` via the `RowResult` dataclass.

CORS is enabled via `corsheaders` middleware for the SPA origin.

### Authentication
`LoginRequiredMiddleware` (in `core/middleware.py`) enforces login for all views except URLs in `settings.LOGIN_EXEMPT_URLS`. For paths matching `settings.LOGIN_EXEMPT_API_PREFIXES`, unauthenticated requests get a JSON 401 instead of a redirect. API auth is session-based — SPAs must fetch CSRF via `/api/auth/csrf/` before POSTing.

## Apps

| App | Responsibility |
|-----|---------------|
| `core` | Shared utilities, AlternateProduct, ShoppingTab, PersistentNotification, TaskRunHistory, locked task runner |
| `main_product_manager` | Master product catalog, search vectors, AI functions (OpenAI) |
| `supplier_manager` | Supplier, Currency, Discount, Category, Manufacturer |
| `supplier_product_manager` | SupplierProduct, file upload/parsing, copy-to-main logic |
| `product_price_manager` | PriceManager rules, MainProductPrice, price Celery tasks |
| `file_manager` | Generic file upload model |
| `blogapp` | Internal article/documentation system |
| `dataframe` | API-driven pipeline composer: pluggable readers + transforms (`registry.py`), JSON pipeline definitions stored on `Dataframe.instructions`, temp upload sessions (`sessions.py`), preview endpoint. No HTML views — consumed by SPA. |
| `api_auth` | Session-auth JSON endpoints (csrf, login, logout, me) for the SPA frontend. |
| `product` | Новый каталог товаров (заменит `main_product_manager`): Product + JSONB `characteristics`, CharacteristicType (M2M к Category, `value_type`/`required`), Category (MPTT) и Brand. REST API с фасетной фильтрацией и импортом через `dataframe`. Import pipeline lives in `product/importer.py`; tests in `product/tests/`. |

## Key Environment Variables

```
SECRET_KEY, DEBUG, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, DB_HOST, DB_PORT
REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND
CELERY_PRICE_UPDATE_MINUTES, CELERY_STOCK_UPDATE_MINUTES, CELERY_LOG_UPDATE_MINUTES
AWS_S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME
IMPORT_COMMIT_BATCH_SIZE  # batch size for product/importer.commit_rows; default 500
```

## Product import worker memory

Product `commit_rows` (`product/importer.py`) writes in chunks of
`IMPORT_COMMIT_BATCH_SIZE` (default 500), each chunk in its own transaction —
the rollback log stays bounded on 50k+ imports. The chunk size is tunable via
env var. After a successful commit, `run_import_commit` calls
`dataframe.sessions.delete_session` to free the cached DataFrame in Redis and
the upload file.

If the worker still hits OOM (`Worker was sent SIGKILL`), run Celery with
`--max-memory-per-child=400000` (KB) so each child recycles after a configurable
RSS ceiling. This is operational, not code-level.

## Import job stages

`ImportJob.stage` (free-form Russian string) is written by `product/tasks.py`
at coarse boundaries so the SPA can show "what the worker is doing": opening
the session, applying the pipeline, validating rows, writing to DB. No
per-row counter — see `STAGE_*` constants at the top of `tasks.py`.

## Dynamic (EAV) characteristics in import

`ImportMapping.dynamic_characteristics` is a list of
`{name_column, value_column, unit_column?}` specs. For each row, the worker
reads those cells, slugifies the name (`slugify(..., allow_unicode=True)`)
and auto-creates a `CharacteristicType` (`value_type='string'`) via
`_resolve_dynamic_types` in `product/importer.py`. Unit is "first-write
wins": when a type already exists with empty `unit` and an entry ships one,
we backfill it; otherwise we never overwrite. Static `mapping.characteristics`
takes precedence on slug collisions. `CharacteristicType.name` uses
`allow_unicode=True` so cyrillic slugs like `'цвет'`/`'вес'` are valid keys.

## Conventions

- UI and model `verbose_name` fields are in **Russian**
- Views are class-based (ListView, CreateView, etc.) with `LoginRequiredMixin`
- Templates use django-template-partials for components, HTMX for interactivity
- Task execution history is logged in `TaskRunHistory` model — check it when debugging Celery issues
- API endpoints under `/api/` use DRF and session auth; the SPA lives at `../price-manager-frontend/` (separate repo working dir)
- New apps should use the `tests/` package layout (see `product/tests/`) instead of a single `tests.py`
- Multi-stage Dockerfile on Python 3.13-slim; production image runs Gunicorn + WhiteNoise
