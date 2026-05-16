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
python manage.py test                          # all tests
python manage.py test core                     # single app
python manage.py test core.tests.MyTestClass  # single class
```

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

### Price Calculation
`PriceManager` rules define: source price field → filters (date range, discount group, category) → `dest_price = source_price * (1 + markup/100) + increase`. Results are pre-calculated into `MainProductPrice` records by Celery tasks.

### File Processing Pipeline
Upload → `setting_upload()` parses file using `Setting` column mappings → creates/updates `SupplierProduct` records → `copy_to_main()` merges into `MainProduct` → Celery tasks propagate prices/stock downstream.

### Celery Task Orchestration
All tasks use `execute_locked_task()` (in `core/task_runner.py`) with Redis distributed locking to prevent concurrent execution. Periodic tasks:
- `update_prices_task()` — recalculates MainProductPrice from PriceManager rules
- `update_stocks_task()` — syncs stock from SupplierProduct to MainProduct
- `update_logs_task()` — writes price history to MainProductLog
- `rebuild_categories_task()` — rebuilds MPPT category tree

### REST API Layer
A JSON API is mounted at `/api/` (router: `price_manager/api_urls.py`) for a decoupled SPA frontend.
- `api_auth` app — session-based auth endpoints: `GET /api/auth/csrf/`, `POST /api/auth/login/`, `POST /api/auth/logout/`, `GET /api/auth/me/`
- `dataframe/api/` — registry (`GET /api/dataframe/registry/`), pipeline CRUD (`/api/dataframe/pipelines/`), upload sessions (`/api/dataframe/sessions/`), preview (`POST /api/dataframe/preview/`)
- `product/api/` — Product library: `/api/products/products/`, `/api/products/categories/`, `/api/products/brands/`, `/api/products/characteristic-types/`, faceted filter via `?char__<name>=`, dataframe-driven import at `/api/products/import/{preview,commit}/`

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
| `product` | Новый каталог товаров (заменит `main_product_manager`): Product + JSONB `characteristics`, CharacteristicType (M2M к Category, `value_type`/`required`), Category (MPTT) и Brand. REST API с фасетной фильтрацией и импортом через `dataframe`. |

## Key Environment Variables

```
SECRET_KEY, DEBUG, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, DB_HOST, DB_PORT
REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND
CELERY_PRICE_UPDATE_MINUTES, CELERY_STOCK_UPDATE_MINUTES, CELERY_LOG_UPDATE_MINUTES
AWS_S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME
```

## Conventions

- UI and model `verbose_name` fields are in **Russian**
- Views are class-based (ListView, CreateView, etc.) with `LoginRequiredMixin`
- Templates use django-template-partials for components, HTMX for interactivity
- Task execution history is logged in `TaskRunHistory` model — check it when debugging Celery issues
- API endpoints under `/api/` use DRF and session auth; the SPA lives at `../price-manager-frontend/` (separate repo working dir)
