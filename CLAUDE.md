# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Start everything:**
```bash
docker compose up --build
```
App runs at `http://localhost:8000`.

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
**Settings module:** `price_manager.settings` (inside `price_manager/price_manager/`).

## Architecture

### Two parallel product catalogs

The codebase has **legacy** and **newer** product systems that coexist:

**Legacy (supplier-centric, UI-driven):**
- `supplier_manager` → `Supplier`, `Currency`, `Category` (MPTT), `Manufacturer`, `Discount`
- `supplier_product_manager` → `SupplierProduct` (supplier's raw price row), `Setting`/`Link` (column-mapping config for Excel imports), `SupplierFile` (upload queue)
- `main_product_manager` → `MainProduct` (canonical product record with multiple price fields, full-text `SearchVectorField` via PostgreSQL GIN index, `pim_api` integration)
- `product_price_manager` → `PriceManager` (markup rules: source price → dest price, with formula), `PriceTag` (per-product-per-rule snapshot), `update_prices()` (bulk apply)

**Newer (API-driven, cleaner domain model):**
- `supplier` app → slimmer `Supplier` model
- `product` app → `Product` (VectorField embedding via pgvector HNSW index for semantic search, characteristics as validated JSONB, `ImportJob`/`CharacteristicMutationJob` async tasks)
- `pricing` app → `PriceType`, `PricingRule`, `ProductPrice`, `Stock`
- `supplier_feed` app → `FeedMapping`, `SupplierFeed`, `SupplierFeedEntry`, `SupplierLink` (supplier price feed ingestion + product matching pipeline)
- `dataframe` app → registry-based ETL pipeline (`@reader` / `@transform` decorators in `dataframe/registry.py`), persisted as `Dataframe` model with a JSON `instructions` field

### Shared infrastructure

**`core/task_runner.py` — `execute_locked_task()`**: Every Celery task should go through this. It provides Redis-based distributed locking (via `cache.add`), wraps the runner in `transaction.atomic()`, and writes a `TaskRunHistory` record with duration and updated-count for every run (success, error, or lock-skipped).

**Celery:** Worker runs as `celery_worker` container, broker/backend via Redis. Tasks are defined as `@shared_task` in each app's `tasks.py`.

**REST API:** DRF, mounted at `/api/`. Each newer app has its own `api/` subpackage with `urls.py`. Auth via `api_auth` (token-based).

**Frontend:** Django templates + HTMX for partial updates, django-tables2 for tabular data, django-crispy-forms + Bootstrap 4, django-autocomplete-light for select widgets.

### Key cross-app dependencies
- `product_price_manager` imports from both `main_product_manager` and `supplier_product_manager` — pricing logic bridges them.
- `supplier_feed` references `product.Product` and `pricing.PriceType` — it belongs to the newer system.
- `main_product_manager.MainProduct._build_searchvector()` calls an external PIM API (`pim_connector`) to enrich the search vector with category/tag/description data.

### Database
PostgreSQL 17 with `pgvector` extension. Two vector indexes in use:
- `GinIndex` on `MainProduct.search_vector` (full-text)
- `HnswIndex` on `Product.embedding` (semantic, cosine similarity, 256-dim)
