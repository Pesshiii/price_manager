# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Always run commands in `price_manager_web` docker service by adding `docker exec price_manager_web` prefix.

```bash
# Full stack (PostgreSQL + Redis + Celery + Django)
docker compose up --build

# Migrations
python manage.py makemigrations
python manage.py migrate

# Tests (run specific app by passing its name)
python manage.py test
python manage.py test core
python manage.py test main_product_manager

# Celery worker (separate terminal)
celery -A price_manager worker -l info

# Celery beat scheduler (separate terminal)
celery -A price_manager beat -l info
```

## Architecture

### Django Apps

| App | Role |
|-----|------|
| `core/` | Base models (ShoppingTab, PersistentNotification, TaskRunHistory), LoginRequiredMiddleware, shared template tags |
| `main_product_manager/` | Central product catalog — MainProduct model, Celery sync/price/stock tasks |
| `supplier_manager/` | Supplier, Manufacturer, Category (MPTT hierarchical) management |
| `supplier_product_manager/` | File upload & parsing (XML/Excel), SupplierProduct model, sync to MainProduct |
| `product_price_manager/` | Rule-based price engine — PriceManager rules, PriceTag output |
| `product/` | API-oriented product views with extended category/price/stock models |
| `dataframe/` | DataFrame model for data transformation workflows |
| `blogapp/` | Blog/content management |
| `price_manager/` | Django project package — settings, URLs, Celery config |

### Data Flow

1. **File upload** → `supplier_product_manager` parses XML/Excel → creates `SupplierProduct` records  
2. **Sync** → user triggers `/supplier/<id>/copytomain/` → `SupplierProduct` records aggregate into `MainProduct`  
3. **Price calculation** → `update_prices` Celery task applies `PriceManager` rules → writes to `MainProductLog` and `MainProduct` price fields  
4. **Stock sync** → `update_stocks` Celery task copies stock from `SupplierProduct` to `MainProduct`

### Celery Tasks & Scheduling

Beat schedule lives in `settings.py` (CELERY_BEAT_SCHEDULE). Active tasks:
- `update_prices` — every 30 min (configurable via `CELERY_PRICE_UPDATE_MINUTES`)
- `update_stocks` — every 15 min (`CELERY_STOCK_UPDATE_MINUTES`)
- `update_logs` — every 60 min (`CELERY_LOG_UPDATE_MINUTES`)
- `cleanup_supplier_files_task` — every 30 min (`CELERY_SUPPLIER_FILES_CLEANUP_MINUTES`)

All tasks use `execute_locked_task()` (in `core/`) to prevent parallel execution. New tasks must follow this pattern.

### Frontend Stack

- **HTMX** (`django-htmx`) — partial page updates without full reloads
- **django-tables2** — sortable/filterable data tables
- **django-filter** — QuerySet filtering on list views
- **django-crispy-forms** + **widget-tweaks** — form rendering with Bootstrap 4
- **django-autocomplete-light** (Select2) — category and product autocomplete fields

### Key Models

- **MainProduct** — central catalog, unique by `(supplier, article, name)`. Price fields: `prime_cost`, `wholesale_price`, `basic_price`, `m_price`, `discount_price`. Has PostgreSQL FTS via `search_vector` (GinIndex).
- **SupplierProduct** — raw supplier data (`supplier_price`, `rrp`, `discount_price`), linked to MainProduct.
- **PriceManager** — pricing rules: source price type → destination price type with markup or fixed increase, filtered by category/discount/RRP presence.
- **Supplier** — master supplier record with currency conversion settings.

### Auth & Middleware

`LoginRequiredMiddleware` (in `core/middleware.py`) redirects unauthenticated users to login for all URLs not in `LOGIN_EXEMPT_URLS`. The app is configured for reverse-proxy deployments (Railway) and trusts `X-Forwarded-*` headers.

## Notes

- Always restart docker container when changes are made and wait untill it restarts.
- UI language is Russian (`LANGUAGE_CODE = 'ru'`). Many `verbose_name` values, messages, and some variable names are in Russian.
- Price field names (`prime_cost`, `m_price`, etc.) reflect legacy business terminology — see `PRICE_TYPES` and `MP_PRICES` constants in `main_product_manager/` before adding or renaming price fields.
- PostgreSQL is required (FTS, MPTT indexing). SQLite will not work.
- Static files are served via WhiteNoise in production. S3 storage is enabled when `AWS_S3_ENDPOINT_URL` + related vars are set.
- For `Claude_in_chorme` actions use localhost:8000 domain. If login is required use name: claude, password: #3hJDRaf6GRzgx
- Project uses HTMX version 4