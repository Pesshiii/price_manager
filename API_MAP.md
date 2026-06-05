# API Map — Price Manager

All routes are mounted under `/api/`. Authentication is **session-based** (Django sessions). The SPA must fetch a CSRF token before any mutating request.

---

## Table of Contents

1. [Auth — `/api/auth/`](#1-auth--apiauth)
2. [Dataframe — `/api/dataframe/`](#2-dataframe--apidataframe)
3. [Products — `/api/products/`](#3-products--apiproducts)
4. [Supplier Feeds — `/api/supplier-feed/`](#4-supplier-feeds--apisupplier-feed)
5. [Suppliers — `/api/suppliers/`](#5-suppliers--apisuppliers)
6. [Transform — `/api/transform/`](#6-transform--apitransform) — SnapshotField, TransformRule, ProductSnapshot (read-only)
7. [Async Job Lifecycle](#7-async-job-lifecycle)
8. [Error Conventions](#8-error-conventions)

---

## 1. Auth — `/api/auth/`

Session-based authentication for the SPA frontend. No JWT — cookies only.

### `GET /api/auth/csrf/`

Sets the `csrftoken` cookie and returns the token value. Must be called before any `POST`/`PUT`/`PATCH`/`DELETE` request from a new session.

**Auth required:** No  
**Response `200`:**
```json
{ "detail": "CSRF cookie set", "csrfToken": "<token>" }
```

---

### `POST /api/auth/login/`

Authenticates a user by username + password and opens a session.

**Auth required:** No  
**Request body:**
```json
{ "username": "string", "password": "string" }
```
**Response `200`** — user object on success:
```json
{ "id": 1, "username": "admin", "email": "...", "first_name": "...", "last_name": "...", "is_staff": true }
```
**Response `401`:**
```json
{ "detail": "Неверный логин или пароль" }
```

---

### `POST /api/auth/logout/`

Destroys the current session.

**Auth required:** Yes  
**Response `204`:** No content.

---

### `GET /api/auth/me/`

Returns the currently authenticated user's profile.

**Auth required:** Yes  
**Response `200`:** Same shape as the login response.  
**Response `403`:** If not authenticated.

---

## 2. Dataframe — `/api/dataframe/`

Pipeline composer for reading and transforming uploaded spreadsheet files. No HTML — consumed entirely by the SPA as the first stage of the product import flow.

### Pipeline concept

A **pipeline** (`Dataframe` model) has:
- **`reader`** — how to read the raw file (e.g. Excel sheet, CSV with delimiter). Validated against the registry.
- **`transforms`** — ordered list of transformation steps (rename columns, filter rows, etc.). Each step is `{func, args}`. Validated against the registry.
- **`source`** — optional `{type: "upload"|"url", url: "..."}`.

### `GET /api/dataframe/registry/`

Returns the full catalogue of registered readers and transforms with their parameter specs. Used by the SPA to render a pipeline editor.

**Auth required:** Yes  
**Response `200`:**
```json
{
  "readers": [
    {
      "name": "excel",
      "label": "Excel",
      "extensions": [".xlsx", ".xls"],
      "args": [
        { "name": "sheet", "type": "string", "label": "Лист", "required": false, "default": null, "choices": null, "help_text": "..." }
      ]
    }
  ],
  "transforms": [
    {
      "name": "rename_columns",
      "label": "Переименовать колонки",
      "args": [...]
    }
  ]
}
```

---

### `GET /api/dataframe/pipelines/`

Lists all saved pipeline configurations.

**Auth required:** Yes  
**Response `200`:** Paginated list of pipeline objects.

---

### `POST /api/dataframe/pipelines/`

Creates a new named pipeline.

**Auth required:** Yes  
**Request body:**
```json
{
  "name": "Supplier A price list",
  "description": "Optional description",
  "instructions": {
    "reader": { "func": "excel", "args": { "sheet": 0 } },
    "transforms": [
      { "func": "rename_columns", "args": { "mapping": { "Артикул": "sku" } } }
    ]
  }
}
```
**Response `201`:** Created pipeline object with `id`, `created_at`, `updated_at`.

---

### `GET /api/dataframe/pipelines/<id>/`

Retrieves a single pipeline by PK.

**Auth required:** Yes  
**Response `200`:** Pipeline object.  
**Response `404`:** Not found.

---

### `PUT /api/dataframe/pipelines/<id>/`

Full replacement update of a pipeline.

**Auth required:** Yes  
**Request body:** Same as create.  
**Response `200`:** Updated pipeline.

---

### `PATCH /api/dataframe/pipelines/<id>/`

Partial update of a pipeline.

**Auth required:** Yes  
**Response `200`:** Updated pipeline.

---

### `DELETE /api/dataframe/pipelines/<id>/`

Deletes a pipeline.

**Auth required:** Yes  
**Response `204`:** No content.

---

### `POST /api/dataframe/sessions/`

Uploads a raw spreadsheet file and returns a `session_id` for subsequent preview and import requests. The file is stored in a temp location; sessions have a ~1 hour TTL in Redis.

**Auth required:** Yes  
**Content-Type:** `multipart/form-data`  
**Form field:** `file` — the spreadsheet (XLS/XLSX/CSV/etc.)

**Response `201`:**
```json
{ "session_id": "abcdef1234...", "filename": "prices.xlsx", "size": 204800 }
```
**Response `400`:** If `file` is missing.

---

### `GET /api/dataframe/sessions/<session_id>/`

Returns metadata for an existing upload session.

**Auth required:** Yes  
**Response `200`:**
```json
{ "session_id": "abcdef1234...", "filename": "prices.xlsx", "size": 204800, "uploaded_at": "..." }
```
**Response `404`:** Session not found or expired.

---

### `DELETE /api/dataframe/sessions/<session_id>/`

Manually deletes a session and its cached DataFrame from Redis. Also accepts `?session_id=<id>` as a fallback.

**Auth required:** Yes  
**Response `204`:** No content.

---

### `POST /api/dataframe/preview/`

Runs the pipeline against an uploaded session and returns a paginated window of rows as JSON. Used by the SPA to show the user what their data looks like after each transform step.

**Key behaviour:**
- Always returns `HTTP 200` once the **reader** succeeds.
- If transform step `K` (0-based) fails, response contains `step_error.step_index == K` and data corresponds to the state **after step K−1**.
- Reader errors (bad file format, expired session) return `404`/`500`.

**Auth required:** Yes  
**Request body:**
```json
{
  "session_id": "abcdef1234...",
  "instructions": {
    "reader": { "func": "excel", "args": { "sheet": 0 } },
    "transforms": []
  },
  "up_to": null,
  "row_limit": 100,
  "offset": 0
}
```

| Field | Required | Default | Notes |
|---|---|---|---|
| `session_id` | ✓ | — | ID from the upload step |
| `instructions` | ✓ | — | Pipeline definition |
| `up_to` | — | `null` | Run only up to (exclusive) this transform index; `null` = run all |
| `row_limit` | — | `100` | 1–1000. Page size for the response |
| `offset` | — | `0` | Row offset for infinite-scroll pagination |

**Response `200`:**
```json
{
  "columns": ["sku", "name", "price"],
  "rows": [["A001", "Widget", 99.9]],
  "total_rows": 5000,
  "returned_rows": 100,
  "offset": 0,
  "has_more": true,
  "step_error": null
}
```
`step_error` shape when a transform fails:
```json
{ "step_index": 2, "message": "Column 'price' not found" }
```

---

## 3. Products — `/api/products/`

The new product catalog. Replaces `main_product_manager`.

### Categories

MPTT tree. Slug is auto-generated from name.

#### `GET /api/products/categories/`

Lists all categories. Supports `?search=<text>`.

**Pagination:** 500 per page (`page_size` up to 5000).  
**Response `200`:** Paginated list:
```json
{ "id": 1, "name": "Электроника", "slug": "elektronika", "parent": null, "level": 0 }
```

#### `POST /api/products/categories/`

Creates a category.

**Request body:**
```json
{ "name": "Смартфоны", "parent": 1 }
```
`slug` and `level` are read-only (auto-computed).

#### `GET /api/products/categories/<id>/`

Retrieves a single category.

#### `PUT/PATCH /api/products/categories/<id>/`

Updates a category.

#### `DELETE /api/products/categories/<id>/`

Deletes a category (blocked if it has children or products — MPTT PROTECT).

---

#### `POST /api/products/categories/<id>/characteristics/`

Adds a `CharacteristicType` to this category's M2M. Two forms:

**Form 1 — link existing type:**
```json
{ "char_type_id": 5 }
```

**Form 2 — inline create + link:**
```json
{ "create": { "name": "цвет", "label": "Цвет", "value_type": "string", "unit": "" } }
```

**Response `201`:** `CharacteristicType` object.  
**Response `400`:** Neither key provided, or inline `create` fails validation (e.g. `name` collision).  
**Response `404`:** `char_type_id` not found.

Adding an already-linked type is idempotent — returns `201` with the existing type.

---

#### `DELETE /api/products/categories/<id>/characteristics/<char_id>/`

Removes a `CharacteristicType` from this category's M2M. Does **not** touch product JSONB data.

**Response `204`:** Removed.  
**Response `404`:** CharacteristicType not found, or not linked to this category.

---

#### `GET /api/products/categories/<id>/characteristics/<char_id>/usage/`

Returns the count of products **in this category** that have a non-null value for this characteristic's JSONB key. Used to warn before removal.

**Response `200`:**
```json
{ "count": 42 }
```
**Response `404`:** CharacteristicType not found.

---

#### `POST /api/products/categories/<id>/assign-products/`

Bulk-assigns products with `category IS NULL` to this category. Products that already have a category are silently skipped (not overwritten). Non-existent IDs are ignored.

**Request body:**
```json
{ "product_ids": [1, 2, 3] }
```

**Response `200`:**
```json
{ "assigned": 2 }
```

`assigned` is the count of products whose category was actually changed (excludes already-assigned and missing).

---

### Brands

Auto-slug from name. Ordered alphabetically.

#### `GET /api/products/brands/`

Lists all brands. Supports `?search=<text>`.

**Pagination:** 500 per page (`page_size` up to 5000).  
**Response fields:** `id`, `name`, `slug`.

#### `POST /api/products/brands/`

Creates a brand. `slug` is auto-generated.

#### `GET/PUT/PATCH/DELETE /api/products/brands/<id>/`

Standard CRUD.

---

### Characteristic Types

Defines the schema for product `characteristics` JSONB values. Auto-created by import for dynamic (EAV) characteristics.

**Important:** `name` (JSONB key) and `value_type` **cannot** be changed via PUT/PATCH — those fields require an async JSONB migration via the dedicated `rename/` and `retype/` sub-endpoints.

#### `GET /api/products/characteristic-types/`

Lists all characteristic types.

**Pagination:** 200 per page (`page_size` up to 2000).  
**Query params:**

| Param | Effect |
|---|---|
| `search` | icontains on `name` or `label` |
| `category` | Filter by category PK; repeatable for OR (`?category=1&category=2`) |
| `value_type` | Filter by type: `string`, `integer`, `float`, `boolean`, `choice` |
| `required` | Filter by required flag: `true`/`false` |
| `name__in` | Comma-separated list of `name` slugs — bulk fetch for import mapping UI |

**Response fields:** `id`, `name`, `label`, `value_type`, `options`, `unit`, `required`, `categories` (list of PKs), `categories_detail` (read-only, expanded `{id, name, level}`).

#### `POST /api/products/characteristic-types/`

Creates a characteristic type.

```json
{
  "name": "цвет",
  "label": "Цвет",
  "value_type": "string",
  "unit": "",
  "required": false,
  "categories": [1, 3]
}
```

#### `GET /api/products/characteristic-types/<id>/`

Retrieves a single type.

#### `PUT/PATCH /api/products/characteristic-types/<id>/`

Updates label, unit, required, categories. Attempting to change `name` or `value_type` returns a `400` with guidance to use the async migration endpoints.

#### `DELETE /api/products/characteristic-types/<id>/`

Deletes the type (does **not** purge the key from product JSONB — do a rename first if needed).

---

### Characteristic Type Mutations (async JSONB migrations)

Because `characteristics` is a JSONB column, changing a type's `name` (key) or `value_type` requires scanning and rewriting every product row. These operations are always async.

**Flow:** `preview` → inspect impact → `commit` → poll job status.

#### `POST /api/products/characteristic-types/<id>/retype/preview/`

Dry-runs a value_type change and returns coercion impact stats. **Synchronous** — scans all products in-process.

**Request body:**
```json
{ "new_value_type": "integer" }
```

**Response `200`:**
```json
{
  "total_with_key": 4200,
  "invalid_count": 17,
  "unique_invalid": [
    { "value": "n/a", "count": 12 },
    { "value": "—", "count": 5 }
  ],
  "truncated": false
}
```

**Response `400`:** If `new_value_type` is missing or unknown.

---

#### `POST /api/products/characteristic-types/<id>/retype/commit/`

Queues an async Celery task to migrate all product JSONB values for this characteristic from the current type to `new_value_type`.

**Request body:**
```json
{
  "new_value_type": "integer",
  "fallback": "drop",
  "default_value": null,
  "value_map": { "n/a": null, "—": null }
}
```

| Field | Required | Values | Notes |
|---|---|---|---|
| `new_value_type` | ✓ | `string`, `integer`, `float`, `boolean`, `choice` | Target type |
| `fallback` | — | `drop` (default), `null`, `default` | What to do when a value can't coerce |
| `default_value` | — | Any JSON | Used when `fallback == "default"` |
| `value_map` | — | `{raw_repr: replacement}` | Per-value override; takes precedence over fallback |

**Response `202`:** A `CharMutationJob` object (see [Job lifecycle](#6-async-job-lifecycle)).

**Worker stages for retype:**
1. `Сканируем товары` — count products with this key
2. `Применяем изменения` — iterate + bulk_update products
3. `Обновляем тип` — save new `value_type` on the CharacteristicType row
4. → success/error

---

#### `POST /api/products/characteristic-types/<id>/rename/preview/`

Dry-runs a key rename and reports collision statistics. **Synchronous.**

**Request body:**
```json
{ "new_name": "colour" }
```

**Response `200`:**
```json
{
  "total_to_rename": 4200,
  "collision_count": 3,
  "collisions": [
    { "product_id": 42, "sku": "A001" }
  ]
}
```

**Response `400`:** If `new_name` is empty, identical to current, or already in use.

---

#### `POST /api/products/characteristic-types/<id>/rename/commit/`

Queues an async Celery task to rename the JSONB key across all products.

**Request body:**
```json
{ "new_name": "colour", "on_conflict": "overwrite" }
```

| `on_conflict` value | Behaviour on collision (product has both keys) |
|---|---|
| `overwrite` (default) | Replace `new_name` with old value |
| `keep_existing` | Drop old key, keep whatever is at `new_name` |
| `skip_row` | Leave the product untouched |

**Response `202`:** A `CharMutationJob` object.

**Worker stages for rename:**
1. `Сканируем товары`
2. `Применяем изменения`
3. `Обновляем тип`
4. → success/error

---

#### `GET /api/products/characteristic-types/jobs/<uuid:job_id>/`

Polls a `CharMutationJob`. See [Job lifecycle](#6-async-job-lifecycle) for the response shape.

**Note:** Only the job's owner (or anonymous, if it was created without auth) can access it.

---

### Products

The main catalog. Products have JSONB `characteristics` validated against `CharacteristicType` definitions.

#### `GET /api/products/products/`

Lists products with filtering and hybrid search.

**Pagination:** 50 per page (`page_size` up to 500).

**Query params:**

| Param | Effect |
|---|---|
| `q` | Full-text search. Hybrid by default: lexical `icontains` on `name`/`sku` merged with pgvector cosine similarity via RRF (k=60). Falls back to pure lexical when no embeddings exist. Returns `503` if embedder is unreachable in `vector`/`hybrid` mode. |
| `search_mode` | `hybrid` (default), `lexical`, `vector` |
| `category` | Filter by category PK; includes all MPTT descendants automatically |
| `category__isnull` | `true` — only products with no category (unassigned pool); `false` — only products that have a category |
| `brand` | Filter by brand PK |
| `status` | `draft`, `active`, `archived` |
| `char__<type_name>` | Filter by JSONB characteristic value. Repeat param for OR. Type-coerced: int → float → bool → string. Example: `?char__цвет=красный&char__цвет=синий` |
| `facets_max_keys` | Used only on `/facets/`. 1–500, default 50 |
| `facets_max_buckets` | Used only on `/facets/`. 1–200, default 30 |

**Response `200`:**
```json
{
  "count": 1234,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 1,
      "sku": "A001",
      "name": "Widget Pro",
      "category": 3,
      "brand": 2,
      "description": "...",
      "status": "active",
      "characteristics": { "цвет": "красный", "вес": 1.5 },
      "image_urls": [],
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

**Response `503`:** Embedder unreachable (vector/hybrid search only):
```json
{ "detail": "Embedding service unavailable: ..." }
```

---

#### `GET /api/products/products/facets/`

Returns aggregated characteristic value counts for the currently-filtered product set. Used by the SPA to render a dynamic faceted filter sidebar.

Accepts the same filter params as the product list (`category`, `brand`, `status`, `q`, `char__*`).

**Response `200`:**
```json
{
  "цвет": {
    "label": "Цвет",
    "unit": "",
    "value_type": "string",
    "buckets": [
      { "value": "красный", "count": 412 },
      { "value": "синий", "count": 307 }
    ]
  },
  "вес": {
    "label": "Вес",
    "unit": "кг",
    "value_type": "float",
    "buckets": [...]
  }
}
```

Keys are limited to the `facets_max_keys` most popular characteristics; each key shows at most `facets_max_buckets` values. Returns `{}` if no filtered products have characteristics.

---

#### `POST /api/products/products/`

Creates a product. `characteristics` is validated against all registered `CharacteristicType` definitions.

**Request body:**
```json
{
  "sku": "A001",
  "name": "Widget Pro",
  "category": 3,
  "brand": 2,
  "description": "",
  "status": "draft",
  "characteristics": { "цвет": "красный" },
  "image_urls": []
}
```
**Response `201`:** Created product.

---

#### `GET /api/products/products/<id>/`

Retrieves a single product.

#### `PUT/PATCH /api/products/products/<id>/`

Updates a product. Characteristics are re-validated on every write.

#### `DELETE /api/products/products/<id>/`

Deletes a product.

---

### Product Import

Two-phase async import: preview validates + shows a sample; commit writes to DB.

**Flow:**
1. Upload a file → get `session_id` (via `POST /api/dataframe/sessions/`)
2. Build / select a pipeline (`/api/dataframe/pipelines/`) and preview it (`/api/dataframe/preview/`)
3. `POST /api/products/import/preview/` → `ImportJob` (kind=`preview`)
4. Poll `/api/products/import/jobs/<id>/` until `status == "success"`
5. Inspect `result.rows` — check `is_valid` flags and validation errors
6. `POST /api/products/import/commit/` → `ImportJob` (kind=`commit`)
7. Poll the new job until `status == "success"`

#### `POST /api/products/import/preview/`

Creates a preview `ImportJob` and queues it on Celery. Returns immediately with a job envelope; the SPA polls for results.

**Request body:**
```json
{
  "session_id": "abcdef...",
  "instructions": { "reader": { "func": "excel", "args": {} }, "transforms": [] },
  "mapping": {
    "sku":         { "column": "Артикул" },
    "name":        { "column": "Наименование" },
    "category":    { "const": "Электроника" },
    "brand":       { "column": "Бренд" },
    "description": { "column": "Описание" },
    "status":      { "const": "active" },
    "characteristics": {
      "цвет": { "column": "Цвет" },
      "вес":  { "column": "Вес (кг)" }
    },
    "dynamic_characteristics": [
      { "name_column": "Имя хар-ки", "value_column": "Значение", "unit_column": "Единица" }
    ]
  },
  "row_limit": 200
}
```

| Field | Required | Notes |
|---|---|---|
| `session_id` | ✓ | From upload step |
| `instructions` | ✓ | Pipeline definition (reader + transforms) |
| `mapping` | ✓ | Column → field mapping. Each field is `{column}` or `{const}` or `{lookup}` |
| `row_limit` | — | 1–10000, default 200. Preview is capped at this many rows |

**Response `202`:** `ImportJob` envelope (pending status).  
**Response `404`:** Session not found.

**Worker stages:**
1. `Открываем сессию` — open the temp file
2. `Применяем pipeline` — run reader + transforms
3. `Валидируем строки` — apply mapping, coerce types, collect errors per row
4. → success (no DB writes in preview)

**Success `result` shape:**
```json
{
  "rows": [
    {
      "row_index": 0,
      "is_valid": true,
      "errors": {},
      "data": { "sku": "A001", "name": "Widget" }
    }
  ],
  "total": 5000,
  "returned": 200,
  "valid": 4983,
  "invalid": 17
}
```

---

#### `POST /api/products/import/commit/`

Same request shape as preview. Creates a commit `ImportJob` that actually writes/upserts products to the DB.

**Auth required:** Yes  
**Response `202`:** `ImportJob` envelope.

**Worker stages:**
1. `Открываем сессию`
2. `Применяем pipeline`
3. `Валидируем строки`
4. `Записываем в БД` — batched upserts (`IMPORT_COMMIT_BATCH_SIZE`, default 500). `rows_total` / `rows_done` updated for a progress bar.

After successful commit:
- The upload session file and its Redis cache are deleted.
- Embedding tasks are queued for all affected products (chunked).

**Success `result` shape:**
```json
{
  "created": 120,
  "updated": 4863,
  "skipped": 0,
  "errors": 17
}
```

---

#### `GET /api/products/import/jobs/<uuid:job_id>/`

Polls an `ImportJob`. Only the job's owner (matched by session) can read it.

**Response `200`:** See [Job lifecycle](#6-async-job-lifecycle).

---

### Category Import

Async import of MPTT category paths from a spreadsheet column. Each row supplies a path-string (e.g. `"Электроника > Смартфоны > Android"`) that is split into segments and resolved against the existing category tree.

**Flow:** same two-phase pattern as product import — preview first, then commit.

#### `POST /api/products/categories/import/preview/`

Creates a preview `ImportJob` (target=`category`) and queues it on Celery.

**Request body:**
```json
{
  "session_id": "abcdef...",
  "instructions": { "reader": { "func": "excel", "args": {} }, "transforms": [] },
  "mapping": {
    "path_column": "Категория",
    "separator": ">"
  },
  "row_limit": 200
}
```

| Field | Required | Notes |
|---|---|---|
| `session_id` | ✓ | From upload step |
| `instructions` | ✓ | Pipeline definition |
| `mapping.path_column` | ✓ | DataFrame column containing the path string |
| `mapping.separator` | — | Segment delimiter, default `>` |
| `row_limit` | — | 1–10000, default 200 |

**Response `202`:** `ImportJob` envelope.

**Worker stages:**
1. `Открываем сессию`
2. `Применяем pipeline`
3. `Валидируем строки`
4. → success (no DB writes)

**Success `result` shape:**
```json
{
  "rows": [
    { "index": 0, "path": "Электроника > Смартфоны", "segments": ["Электроника", "Смартфоны"], "status": "new" }
  ],
  "total": 50,
  "returned": 50,
  "new": 12,
  "exists": 35,
  "invalid": 3
}
```

`status` per row: `new` — will be created; `exists` — already in tree; `invalid` — empty/malformed path.

---

#### `POST /api/products/categories/import/commit/`

Same request shape as category preview. Commits only `status=new` rows to the DB.

**Response `202`:** `ImportJob` envelope.

**Worker stages:**
1. `Открываем сессию`
2. `Применяем pipeline`
3. `Валидируем строки`
4. `Записываем в БД`

After a successful commit the upload session is deleted from Redis.

**Success `result` shape:**
```json
{
  "created": 12,
  "skipped": 35,
  "invalid": 3,
  "errors": []
}
```

`created` counts individual category **nodes** created (not paths). A new path `A > B > C` where `A` already exists creates 2 nodes (`B` and `C`).

---

#### `GET /api/products/categories/import/jobs/<uuid:job_id>/`

Polls a category `ImportJob`. Only the job's owner can read it.

**Response `200`:** See [Job lifecycle](#6-async-job-lifecycle).

---

## 4. Supplier Feeds — `/api/supplier-feed/`

Manages the workflow of ingesting and matching supplier price lists against the product catalog.

### Lifecycle

```
draft → (upload files) → process → processing → matched / partial → (resolve queue) → done
                                                                   ↓
                                                                 error
```

- **`draft`** — newly created session; files can be uploaded and deleted.
- **`processing`** — Celery matching task is running.
- **`matched`** — all entries auto-matched above the threshold.
- **`partial`** — some entries need manual review (match queue).
- **`done`** — all queue entries resolved (matched or skipped).
- **`error`** — matching task failed.

---

### Feed Mappings

Configuration templates that describe how to parse a supplier's file format. Each mapping references a **Dataframe pipeline** (`dataframe` FK) which is applied to every uploaded file before matching — raw files are never read directly. Column names (`supplier_sku_column`, `identity_columns`, `variable_columns`) refer to the **output** of the pipeline, not the raw file.

#### `GET /api/supplier-feed/mappings/`

Lists all feed mapping configurations, ordered by supplier + name.

**Response fields:** `id`, `supplier`, `name`, `dataframe` (PK), `dataframe_detail` `{id, name}`, `supplier_sku_column`, `identity_columns`, `variable_columns`, `auto_match_threshold`, `product_name_column`, `product_sku_column`.

`product_name_column` and `product_sku_column` are optional column hints used by the `create-product` UI: they tell the SPA which pipeline-output column to pre-fill the new-product name / SKU fields from.

#### `POST /api/supplier-feed/mappings/`

Creates a feed mapping. `dataframe` is required — create a pipeline first via `POST /api/dataframe/pipelines/`.

```json
{
  "supplier": 1,
  "name": "Прайс-лист основной",
  "dataframe": 3,
  "supplier_sku_column": "sku",
  "identity_columns": ["sku", "name"],
  "variable_columns": ["price", "stock"],
  "auto_match_threshold": 0.92,
  "product_name_column": "name",
  "product_sku_column": "sku"
}
```

#### `GET /api/supplier-feed/mappings/<id>/`

Retrieves a single mapping.

#### `PUT/PATCH /api/supplier-feed/mappings/<id>/`

Updates a mapping.

#### `DELETE /api/supplier-feed/mappings/<id>/`

Deletes a mapping. Returns `409 Conflict` if any `SupplierFeed` sessions reference it.

---

### Supplier Feeds (Sessions)

Each `SupplierFeed` is one import session for a supplier.

#### `GET /api/supplier-feed/feeds/`

Lists feed sessions. Supports `?supplier=<id>` and `?status=<status>` filters. Ordered by `-created_at`.

**Response fields:** `id`, `supplier`, `feed_mapping`, `status`, `session_ids`, `error`, `created_at`.

#### `POST /api/supplier-feed/feeds/`

Creates a new feed session in `draft` status.

```json
{ "supplier": 1, "feed_mapping": 2 }
```

#### `GET /api/supplier-feed/feeds/<id>/`

Retrieves detail view — same fields plus computed stats:
- `total` — total number of entries parsed from uploaded files
- `matched` — entries with a confirmed product link
- `queued` — unresolved entries (product=null, not skipped)
- `skipped` — entries marked "not found"

#### `DELETE /api/supplier-feed/feeds/<id>/`

Deletes a feed session and all its entries.

---

#### `POST /api/supplier-feed/feeds/<id>/upload/`

Uploads a file to a feed session. Stores it as a dataframe session and appends the `session_id` to the feed's `session_ids` list.

**Content-Type:** `multipart/form-data`  
**Form field:** `file`

**Response `201`:** Session metadata:
```json
{ "session_id": "abcdef...", "filename": "prices.xlsx", "size": 204800, "uploaded_at": "..." }
```
**Response `400`:** File not provided.

---

#### `DELETE /api/supplier-feed/feeds/<id>/files/<session_id>/`

Removes an uploaded file from a **draft** feed. Deletes the dataframe session and removes it from the feed's `session_ids`.

**Response `204`:** No content.  
**Response `403`:** Feed is not in `draft` status.  
**Response `404`:** Session not found in this feed.

---

#### `POST /api/supplier-feed/feeds/<id>/process/`

Transitions a draft feed to `processing` and queues the Celery matching task (`run_feed_matching_task`).

The task applies the `FeedMapping.dataframe` pipeline to each uploaded session file (`dataframe.services.apply()`), concatenates the resulting rows, runs auto-matching against the product catalog (cosine similarity threshold from `FeedMapping.auto_match_threshold`), and creates `SupplierFeedEntry` rows. If the pipeline fails for any file the feed transitions to `error` — partial data is never used.

**Response `202`:** Current feed state.  
**Response `400`:** Feed is not in `draft` status.

---

#### `GET /api/supplier-feed/feeds/<id>/queue/`

Returns a paginated list of **unresolved** entries (product=null, skipped=false) for manual matching review.

`data` contains the union of identity and variable columns from `FeedMapping` (both available for display). `match_candidates` is a list of top-N catalog products with cosine similarity scores, denormalized at match time. `best_score` is the similarity score of the top candidate (`null` if no candidates exist — indicates the embedder may have been unavailable during matching).

**Sort order:** `best_score DESC NULLS FIRST` — entries without candidates appear first (anomalies), then entries sorted by descending similarity. Typical review flow: resolve high-score entries manually, then bulk-create new products for the low-score tail.

**Pagination:** 20 per page (`page_size` up to 200).

**Response `200`:**
```json
{
  "count": 47,
  "next": "...",
  "results": [
    {
      "id": 101,
      "supplier_sku": "XYZ-999",
      "data": { "name": "Gear Pump", "price": 450.0 },
      "match_candidates": [
        { "product_id": 42, "score": 0.88, "name": "Gear Pump 100", "sku": "GP-001", "category": "Насосы", "brand": "Grundfos" }
      ],
      "best_score": 0.88
    }
  ]
}
```

---

#### `POST /api/supplier-feed/feeds/<id>/queue/bulk-create-products/`

Creates a new `Product` (status=`draft`) + `SupplierLink` for **every** remaining unresolved entry (product=null, skipped=false) in one request. Designed for the tail of the queue where entries have low similarity scores and are unlikely to match existing catalog products.

Before calling, the SPA shows a confirmation dialog pre-filled with `FeedMapping.product_name_column` (if configured) to let the user confirm or change which data column to use as the product name.

**Request body:**
```json
{ "name_column": "name" }
```

| Field | Required | Notes |
|---|---|---|
| `name_column` | ✓ | Column from `entry.data` to use as `Product.name` |

**SKU resolution:** `entry.data[FeedMapping.product_sku_column]` if `product_sku_column` is configured and the value is non-empty; otherwise `entry.supplier_sku`.

**Error handling:** skip-and-continue — entries that fail (SKU conflict, missing/empty `name_column`) are left untouched in the queue. Successful entries are resolved atomically.

**Auto-done:** If the queue empties after the operation, the feed transitions to `done`.

**Response `400`:** `name_column` not provided.

**Response `200`:**
```json
{
  "created": 42,
  "failed": 3,
  "errors": [
    { "entry_id": 107, "reason": "Товар с артикулом «ABC-001» уже существует." },
    { "entry_id": 112, "reason": "Колонка «name» пуста или отсутствует." }
  ]
}
```

---

#### `POST /api/supplier-feed/feeds/<id>/queue/<entry_id>/resolve/`

Resolves one queued entry by either confirming a product match or skipping it.

**Request body — confirm match:**
```json
{ "product_id": 42 }
```
Creates or updates a permanent `SupplierLink(supplier, supplier_sku → product)`.

**Request body — skip:**
```json
{ "skipped": true }
```

**Auto-done:** If resolving this entry empties the queue, the feed's status automatically transitions to `done`.

**Response `200`:** Updated entry.  
**Response `400`:** Entry already resolved, or neither `product_id` nor `skipped` provided, or `product_id` not found.  
**Response `404`:** Entry not found in this feed.

---

#### `POST /api/supplier-feed/feeds/<id>/queue/<entry_id>/create-product/`

Creates a new `Product` (status=`draft`) from an unresolved queue entry, links it to the supplier SKU, and resolves the entry — all in one transaction.

**Request body:**
```json
{ "sku": "MY-SKU-001", "name": "New Product Name" }
```

**Auto-done:** Same as `resolve` — if this was the last queued entry the feed transitions to `done`.

**Response `201`:** Updated entry.  
**Response `400`:** Entry already resolved, `sku`/`name` missing, or a Product with `sku` already exists.  
**Response `404`:** Entry not found in this feed.

---

#### `POST /api/supplier-feed/feeds/<id>/queue/<entry_id>/ignore/`

Marks an unresolved queue entry as permanently ignored. Creates an **игнор-линк** (`SupplierLink` with `product=null`) so the same supplier SKU is automatically skipped in future feeds without going through the matching queue.

**Request body:** empty (`{}`)

**Auto-done:** If this was the last queued entry the feed transitions to `done`.

**Response `200`:** Updated entry.  
**Response `400`:** Entry already resolved or skipped.  
**Response `404`:** Entry not found in this feed.

---

### Supplier Links

Permanent supplier-SKU → product mappings. A link with `product=null` is an **игнор-линк** — its SKU is silently skipped during matching rather than entering the manual queue.

#### `GET /api/supplier-feed/links/`

Lists all supplier links. Supports filters:

| Param | Effect |
|---|---|
| `supplier` | Filter by supplier PK |
| `supplier_sku` | icontains search on supplier SKU |
| `product` | Filter by product PK |

**Response fields:** `id`, `supplier` `{id, name}`, `supplier_sku`, `product` `{id, name, sku}` or `null` for игнор-линки.

#### `PATCH /api/supplier-feed/links/<id>/`

Reassigns a link to a different product.

**Request body:**
```json
{ "product_id": 99 }
```
**Response `200`:** Updated link.  
**Response `400`:** Product not found.

#### `DELETE /api/supplier-feed/links/<id>/`

Deletes a supplier link permanently.

---

## 5. Suppliers — `/api/suppliers/`

Simple CRUD for supplier records.

#### `GET /api/suppliers/`

Lists all suppliers.

**Response fields:** `id`, `name`.

#### `POST /api/suppliers/`

Creates a supplier.
```json
{ "name": "ООО Поставщик" }
```

#### `GET /api/suppliers/<id>/`

Retrieves a supplier.

#### `PUT/PATCH /api/suppliers/<id>/`

Updates a supplier name.

#### `DELETE /api/suppliers/<id>/`

Deletes a supplier. Blocked if referenced by feeds or feed mappings (CASCADE or PROTECT depending on model).

---

## 6. Transform — `/api/transform/`

Configuration of named, typed fields that transform rules can reference in formulas and conditions.

### SnapshotField

#### `GET /api/transform/snapshot-fields/`

Lists all snapshot fields.

**Auth required:** Yes  
**Pagination:** 200 per page (`page_size` up to 1000).  
**Response fields:** `id`, `slug`, `name`, `value_type`, `description`.

---

#### `POST /api/transform/snapshot-fields/`

Creates a snapshot field.

**Auth required:** Yes  
**Request body:**
```json
{
  "slug": "price",
  "name": "Цена",
  "value_type": "number",
  "description": "Розничная цена товара"
}
```

| Field | Required | Notes |
|---|---|---|
| `slug` | ✓ | Unique URL-safe identifier |
| `name` | ✓ | Human-readable label |
| `value_type` | ✓ | One of `number`, `string`, `boolean` |
| `description` | — | Optional free text |

**Response `201`:** Created snapshot field.  
**Response `400`:** Duplicate `slug`, or invalid `value_type`.

---

#### `GET /api/transform/snapshot-fields/<id>/`

Retrieves a single snapshot field.

**Auth required:** Yes  
**Response `200`:** Snapshot field object.

---

#### `PUT/PATCH /api/transform/snapshot-fields/<id>/`

Updates a snapshot field.

**Auth required:** Yes  
**Response `200`:** Updated object.

---

#### `DELETE /api/transform/snapshot-fields/<id>/`

Deletes a snapshot field.

**Auth required:** Yes  
**Response `204`:** No content.

---

### TransformRule

Rules that map a feed column formula to a snapshot field, scoped to a feed mapping.

#### `GET /api/transform/rules/`

Lists all transform rules. Optionally filter by feed mapping.

**Auth required:** Yes  
**Pagination:** 200 per page (`page_size` up to 1000).  
**Query params:**

| Param | Type | Notes |
|---|---|---|
| `feed_mapping` | int | Return only rules for this FeedMapping ID |

**Response fields:** `id`, `feed_mapping`, `target_field`, `priority`, `condition`, `formula`.

---

#### `POST /api/transform/rules/`

Creates a transform rule.

**Auth required:** Yes  
**Request body:**
```json
{
  "feed_mapping": 1,
  "target_field": 1,
  "priority": 10,
  "condition": null,
  "formula": {"type": "literal", "value": 100}
}
```

| Field | Required | Notes |
|---|---|---|
| `feed_mapping` | ✓ | FK to FeedMapping (CASCADE on delete) |
| `target_field` | ✓ | FK to SnapshotField (PROTECT on delete) |
| `priority` | ✓ | Integer; lower value = higher priority |
| `condition` | — | JSON condition tree; `null` means always fires |
| `formula` | ✓ | JSON formula; no schema validation at API layer |

**Response `201`:** Created rule.  
**Response `400`:** Missing required field.

---

#### `GET /api/transform/rules/<id>/`

Retrieves a single rule.

**Auth required:** Yes  
**Response `200`:** Rule object.

---

#### `PUT/PATCH /api/transform/rules/<id>/`

Updates a rule.

**Auth required:** Yes  
**Response `200`:** Updated object.

---

#### `DELETE /api/transform/rules/<id>/`

Deletes a rule.

**Auth required:** Yes  
**Response `204`:** No content.

---

### ProductSnapshot

Read-only materialized snapshots of a supplier's data for a product. Written by the transform engine (Celery task, slice #114) — not writable via API.

#### `GET /api/transform/snapshots/`

Lists all product snapshots.

**Auth required:** Yes  
**Pagination:** 200 per page (`page_size` up to 1000).  
**Query params:**

| Param | Type | Notes |
|---|---|---|
| `product` | int | Filter by product ID |
| `supplier` | int | Filter by supplier ID |

Both params are combinable (AND semantics).

**Response fields:** `id`, `product`, `supplier`, `source_feed` (nullable FK to SupplierFeed), `data` (JSON object, keys = SnapshotField slugs), `updated_at`.

---

#### `GET /api/transform/snapshots/<id>/`

Retrieves a single snapshot.

**Auth required:** Yes  
**Response `200`:** Snapshot object.  
**Response `404`:** Not found.

---

`POST`, `PUT`, `PATCH`, `DELETE` → **`405 Method Not Allowed`** (snapshots are written by the transform engine, not the API).

---

## 7. Async Job Lifecycle

`ImportJob` and `CharacteristicMutationJob` share the same envelope and polling pattern.

### Status values

| `status` | Meaning |
|---|---|
| `pending` | Queued, not yet picked up by a worker |
| `running` | Worker is executing; `stage` shows the current step |
| `success` | Completed successfully; see `result` |
| `error` | Failed; see `error` string |

### Job response shape

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "kind": "commit",
  "status": "running",
  "stage": "Записываем в БД",
  "rows_total": 5000,
  "rows_done": 1500,
  "result": null,
  "error": "",
  "created_at": "2026-05-27T10:00:00Z",
  "started_at": "2026-05-27T10:00:01Z",
  "finished_at": null
}
```

`CharMutationJob` additionally includes `char_type` (PK) and `payload`.

### Recommended polling interval

Poll every 1–2 seconds while `status` is `pending` or `running`. Stop when `success` or `error`.

### Progress bar

Use `rows_done / rows_total` as a fraction. Both are `0` until the worker reaches the DB-write or mutation stage.

---

## 8. Error Conventions

| Status | Meaning |
|---|---|
| `400 Bad Request` | Validation error — response body is `{field: [messages]}` or `{detail: "..."}` |
| `401 Unauthorized` | Not authenticated (JSON, not redirect, for `/api/` paths) |
| `403 Forbidden` | Authenticated but not allowed |
| `404 Not Found` | Object or session does not exist |
| `409 Conflict` | Business rule violation (e.g. deleting a mapping that has feeds) |
| `500 Internal Server Error` | Reader-stage pipeline error |
| `503 Service Unavailable` | Embedding service (Ollama) unreachable during vector/hybrid search |

All responses are JSON. The `LoginRequiredMiddleware` returns a `401` JSON (not an HTML redirect) for unauthenticated requests to paths matching `LOGIN_EXEMPT_API_PREFIXES` (i.e. all `/api/` routes).
