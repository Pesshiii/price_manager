# Frontend Page Map

Reference for backend developers: every page, its route, API endpoints it calls, and key behaviour.

---

## Auth

### Login — `/login`
**File:** `src/pages/LoginPage.tsx`

| Action | Endpoint |
|--------|----------|
| Submit credentials | `POST /auth/login/` (via AuthContext) |
| Session check on mount | `GET /auth/me/` |
| CSRF init | `GET /auth/csrf/` |

- Public route (no `RequireAuth`).
- On success navigates to `/`.

---

## Dashboard — `/`
**File:** `src/pages/DashboardPage.tsx`

No API calls. Static welcome page.

---

## Dataframe (Pipeline) Feature

### Pipeline List — `/dataframe`
**File:** `src/features/dataframe/pages/DataframeListPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load pipelines | `GET /dataframe/pipelines/` |
| Delete pipeline | `DELETE /dataframe/pipelines/{id}/` |

- Table with name, reader, transform count, updated-at.
- Delete shows confirmation modal; invalidates `dataframeKeys.pipelines()`.

### Pipeline Editor — `/dataframe/new`, `/dataframe/:id`
**File:** `src/features/dataframe/pages/DataframeEditorPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load existing pipeline | `GET /dataframe/pipelines/{id}/` |
| Create pipeline | `POST /dataframe/pipelines/` |
| Update pipeline | `PUT /dataframe/pipelines/{id}/` |
| Upload file for preview | `POST /dataframe/sessions/` |
| Run preview | `POST /dataframe/preview/` |

- Undo/redo toolbar + `DataframeBuilder` visual editor.
- Preview is live (not polled) — result returns synchronously from `/dataframe/preview/`.
- Column headers in preview table open a transform menu (column-aware transforms only).

---

## Product Feature

### Product List — `/products`
**File:** `src/features/product/pages/ProductListPage.tsx`

| Action | Endpoint |
|--------|----------|
| List products | `GET /products/products/` |
| Facets for sidebar | `GET /products/products/facets/` |
| List categories (filter) | `GET /products/categories/` |
| List brands (filter) | `GET /products/brands/` |
| Delete product | `DELETE /products/products/{id}/` |

- Sidebar facets use the **same** filter params as the list (`char__<name>` repeatable = OR).
- Pagination: `?page=N&page_size=N`, total from `count`.
- Invalidates `productKeys.all` on delete.

### Product Detail — `/products/:id`
**File:** `src/features/product/pages/ProductDetailPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load product | `GET /products/products/{id}/` |
| Load categories (labels) | `GET /products/categories/` |
| Load brands (labels) | `GET /products/brands/` |
| Load char-type metadata | `GET /products/characteristic-types/?name__in=...` |
| Delete product | `DELETE /products/products/{id}/` |
| Load snapshots | `GET /api/transform/snapshots/?product={id}` |

- Char-type metadata fetched with `name__in` bulk lookup to render labels + units.
- "Снимки поставщиков" collapsible section below characteristics: table of `ProductSnapshot` records keyed by supplier, columns = supplier name + one column per `SnapshotField` slug present in any snapshot. Verify `?product` filter exists in API before implementing.

### Product Editor — `/products/new`, `/products/:id/edit`
**File:** `src/features/product/pages/ProductEditorPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load product (edit mode) | `GET /products/products/{id}/` |
| Create product | `POST /products/products/` |
| Update product | `PATCH /products/products/{id}/` |

- Invalidates `productKeys.all` on success.
- Characteristic-specific field errors parsed from DRF response.

### Categories — `/products/categories`
**File:** `src/features/product/pages/CategoriesPage.tsx`

| Action | Endpoint |
|--------|----------|
| List categories | `GET /products/categories/` |
| Create category | `POST /products/categories/` |
| Delete category | `DELETE /products/categories/{id}/` |

- Hierarchical `CategoryTree` component.
- Modal for root or sub-category creation.
- Invalidates `categoryKeys.all` on create/delete.
- Links to `/products/categories/import`.

### Category Detail — `/products/categories/:id`
**File:** `src/features/product/pages/CategoryDetailPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load category | `GET /products/categories/{id}/` |
| List linked char-types | `GET /products/characteristic-types/?category={id}` |
| Search char-types to add | `GET /products/characteristic-types/?search=...` |
| Link existing char-type | `POST /products/categories/{id}/characteristics/` `{char_type_id}` |
| Fetch char-type usage count | `GET /products/categories/{id}/characteristics/{charId}/usage/` |
| Remove char-type link | `DELETE /products/categories/{id}/characteristics/{charId}/` |
| List unassigned products | `GET /products/products/?category__isnull=true&q=...&page=N&page_size=N` |
| Assign products | `POST /products/categories/{id}/assign-products/` `{product_ids:[...]}` |

**Layout:** two `Card withBorder` sections stacked.

**Characteristics section:**
- Table of linked `CharacteristicType` entries.
- `MultiSelect` with debounced search (~300 ms) to pick existing types; excludes already-linked IDs client-side.
- "Создать новый тип →" text link navigates to `/products/characteristics`.
- Remove: trash `ActionIcon` opens a `Popover` that lazily fetches usage count, shows "Используется в N продуктах. Удалить?" with Confirm/Cancel.

**Products section:**
- Paginated table of unassigned products (`?category__isnull=true`), debounced search input above.
- Checkboxes; selected `Set<number>` persists across page changes.
- "Назначить (N)" button disabled when set is empty; fires assign mutation.

**Invalidation:**
- Add/remove char-type link → `charTypeKeys.all` + `categoryKeys.all`.
- Assign products → `productKeys.all` + `categoryKeys.all`.

**Navigation entry:** category name in `CategoryTree` / `CategoryNodeRow` is a `Link` to this page.

---

### Category Import — `/products/categories/import`
**File:** `src/features/product/pages/CategoryImportPage.tsx`

| Action | Endpoint |
|--------|----------|
| List pipelines | `GET /dataframe/pipelines/` |
| Upload file | `POST /dataframe/sessions/` |
| Run dataframe preview | `POST /dataframe/preview/` |
| Delete session | `DELETE /dataframe/sessions/{sessionId}/` |
| Preview category import | `POST /products/categories/import/preview/` |
| Commit category import | `POST /products/categories/import/commit/` |
| Poll preview job | `GET /products/categories/import/jobs/{jobId}/` |
| Poll commit job | `GET /products/categories/import/jobs/{jobId}/` |
| Save ad-hoc pipeline | `POST /dataframe/pipelines/` |

**Polling:** preview & commit jobs polled every **2 s** until terminal status (`success` / `error`).

- 3-step wizard: Source → Mapping (path column) → Import.
- Saved pipeline vs ad-hoc mode toggle.
- Invalidates `categoryKeys.all` after successful commit.

### Brands — `/products/brands`
**File:** `src/features/product/pages/BrandsPage.tsx`

| Action | Endpoint |
|--------|----------|
| List brands | `GET /products/brands/` |
| Create brand | `POST /products/brands/` |
| Delete brand | `DELETE /products/brands/{id}/` |

- Invalidates `brandKeys.all` on create/delete.

### Characteristic Types — `/products/characteristics`
**File:** `src/features/product/pages/CharacteristicTypesPage.tsx`

| Action | Endpoint |
|--------|----------|
| List char types (filtered) | `GET /products/characteristic-types/` (`page_size=2000`) |
| List categories (filter chip) | `GET /products/categories/` |
| Create char type | `POST /products/characteristic-types/` |
| Edit (safe fields) | `PATCH /products/characteristic-types/{id}/` |
| Rename (async job) | `POST /products/characteristic-types/{id}/rename/preview/` → `…/commit/` |
| Retype (async job) | `POST /products/characteristic-types/{id}/retype/preview/` → `…/commit/` |
| Delete char type | `DELETE /products/characteristic-types/{id}/` |
| Poll rename/retype job | `GET /products/characteristic-types/jobs/{jobId}/` every 2 s |

**Filter toolbar:** search (debounced 300 ms), category MultiSelect, value_type Select, required SegmentedControl.

**Edit modal split:**
- *Safe* fields (`label`, `unit`, `options`, `required`, `categories`) → plain `PATCH`.
- *Migrating* fields (`name`, `value_type`) → wizard after saving safe fields. Rename before retype.

**Rename wizard:** `previewRename` → if `collision_count === 0` auto-commits; else shows collision list + `on_conflict` selector.

**Retype wizard:** `previewRetype` → if `invalid_count === 0` auto-commits; else conflict modal. If `unique_invalid.length < 10` shows per-value override table, else single fallback Select.

**Polling:** job status polled every 2 s; on terminal success invalidates `charTypeKeys.all` + `productKeys.all`.

### Product Import — `/products/import`
**File:** `src/features/product/pages/ImportPage.tsx`

| Action | Endpoint |
|--------|----------|
| List pipelines | `GET /dataframe/pipelines/` |
| Upload file | `POST /dataframe/sessions/` |
| Run dataframe preview | `POST /dataframe/preview/` |
| Delete session | `DELETE /dataframe/sessions/{sessionId}/` |
| Load char types (mapping) | `GET /products/characteristic-types/` |
| Preview product import | `POST /products/import/preview/` |
| Commit product import | `POST /products/import/commit/` |
| Poll preview job | `GET /products/import/jobs/{jobId}/` |
| Poll commit job | `GET /products/import/jobs/{jobId}/` |
| Save ad-hoc pipeline | `POST /dataframe/pipelines/` |

**Polling:** preview & commit jobs polled every **2 s** until terminal status (`success` / `error`).

- 3-step wizard: Source → Mapping → Import.
- Mapping supports static product fields + characteristic types (keyed by `CharacteristicType.name`) + dynamic EAV rows (`DynamicCharSpec`).
- Inline creation of new char types; backend re-attaches M2M on commit.
- Full wizard state persisted in `localStorage` (`product-import-state-v2`); F5 mid-commit resumes polling.
- Notification dedup via refs keyed `${job.id}:${status}`.
- On successful commit invalidates `productKeys.all + categoryKeys.all + brandKeys.all`.

**Import mapping shape:**
```ts
type FieldMapping = { column: string } | { const: unknown };
interface ImportMapping {
  sku?: FieldMapping;
  name?: FieldMapping;
  category?: FieldMapping;
  brand?: FieldMapping;
  description?: FieldMapping;
  status?: FieldMapping;
  characteristics?: Record<string, FieldMapping>; // keyed by CharacteristicType.name
  dynamic_characteristics?: DynamicCharSpec[];    // {name_column, value_column, unit_column?}
}
```

---

## Supplier Feature

### Suppliers List — `/suppliers`
**File:** `src/features/supplier/pages/SuppliersPage.tsx`

| Action | Endpoint |
|--------|----------|
| List suppliers | `GET /suppliers/` |
| Create supplier | `POST /suppliers/` |
| Update supplier | `PATCH /suppliers/{id}/` |
| Delete supplier | `DELETE /suppliers/{id}/` |

- 409 on delete = supplier in use, shown as error notification.
- Invalidates `supplierKeys.all` on create/update/delete.

### Supplier Detail — `/suppliers/:id`
**File:** `src/features/supplier/pages/SupplierDetailPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load supplier | `GET /suppliers/{id}/` |
| List feed mappings | `GET /supplier-feed/mappings/?supplier={id}` |
| List feeds | `GET /supplier-feed/feeds/?supplier={id}` |
| Create feed | `POST /supplier-feed/feeds/` |
| Delete feed mapping | `DELETE /supplier-feed/mappings/{id}/` |

- Two sections: Mappings table + Feeds table.
- 409 on mapping delete = mapping in use.
- Links to mapping editor, feed detail, and supplier links.

### Feed Mapping Create — `/suppliers/:id/mappings/new`
**File:** `src/features/supplier/pages/FeedMappingCreatePage.tsx`

| Action | Endpoint |
|--------|----------|
| List pipelines | `GET /dataframe/pipelines/` |
| Create pipeline (inline) | `POST /dataframe/pipelines/` |
| Create mapping | `POST /supplier-feed/mappings/` |

- 2-step stepper: Pipeline selection → Mapping config.
- `NewPipelineDrawer` for inline pipeline creation without leaving the page.
- Mapping fields: name, SKU column, identity columns, variable columns, auto-match threshold (0–1).

### Feed Mapping Edit — `/suppliers/:id/mappings/:mappingId/edit`
**File:** `src/features/supplier/pages/FeedMappingEditPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load mapping | `GET /supplier-feed/mappings/{id}/` |
| List pipelines | `GET /dataframe/pipelines/` |
| Create pipeline (inline) | `POST /dataframe/pipelines/` |
| Update mapping | `PATCH /supplier-feed/mappings/{id}/` |
| List markup sets | `GET /supplier-feed/markup-sets/?mapping={id}` |
| Create markup set | `POST /supplier-feed/markup-sets/` |
| Update markup set | `PATCH /supplier-feed/markup-sets/{id}/` |
| Delete markup set | `DELETE /supplier-feed/markup-sets/{id}/` |
| Create markup rule | `POST /supplier-feed/markup-rules/` |
| Update markup rule | `PATCH /supplier-feed/markup-rules/{id}/` |
| Delete markup rule | `DELETE /supplier-feed/markup-rules/{id}/` |

- Single-page form (no stepper).
- Pipeline change triggers a confirmation modal.
- "Правила трансформации (N) →" link card navigates to the rules page.
- **Наценки (MarkupSets):** section below the main form. Lists `FeedMarkupSet` cards (name, `price_column → output_column`, rule count). Add/edit opens `MarkupSetModal`; delete immediately via `DELETE`. Modal: set fields + rule table with ↑/↓ reorder; saved as a batch (set `PATCH` + per-rule `POST/PATCH/DELETE`). `price_column` / `output_column` are `Autocomplete` from `variable_columns`. Rule order = row position × 10. Section only appears in edit mode (markup sets require an existing mapping FK).

### Transform Rules — `/suppliers/:id/mappings/:mappingId/rules`
**File:** `src/features/transform/pages/TransformRulesPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load mapping (breadcrumb) | `GET /supplier-feed/mappings/{id}/` |
| List rules for mapping | `GET /api/transform/rules/?feed_mapping={id}` |
| List snapshot fields | `GET /api/transform/snapshot-fields/` |
| Create rule | `POST /api/transform/rules/` |
| Update rule | `PATCH /api/transform/rules/{id}/` |
| Delete rule | `DELETE /api/transform/rules/{id}/` |

- Table of rules ordered by `priority` (lower = higher priority).
- Inline create/edit via modal; modal contains the formula + condition builder.
- **Formula builder:** bounded structured builder (depth ≤ 2). Top-level type Select (`copy` / `literal` / `arithmetic` / `map` / `if`). Sub-formula slots (`arithmetic` left/right, `if` then/else, `map` input) limited to `copy` or `literal`. "Расширенный режим" toggle exposes raw JSON textarea for deeper nesting.
- **Condition builder:** flat list of leaf comparisons joined by single AND/OR toggle; "Без условия" toggle maps to `condition: null`. Leaf fields: `source` Select (`feed` / `char` / `brand` / `category`), `key` TextInput (hidden for brand/category), `op` Select, `value` input.
- `target_field` Select populated from snapshot fields; "Создать поле →" link navigates to `/transform/snapshot-fields`.
- Invalidates `transformKeys.rules(mappingId)` on create/update/delete.

### Supplier Feed — `/suppliers/:id/feeds/:feedId`
**File:** `src/features/supplier/pages/SupplierFeedPage.tsx`

| Action | Endpoint |
|--------|----------|
| Load feed (with polling) | `GET /supplier-feed/feeds/{feedId}/` every 2 s |
| Load supplier | `GET /suppliers/{id}/` |
| Load mapping | `GET /supplier-feed/mappings/{mappingId}/` |
| Upload file | `POST /supplier-feed/feeds/{feedId}/upload/` |
| Delete file | `DELETE /supplier-feed/feeds/{feedId}/files/{sessionId}/` |
| Process feed | `POST /supplier-feed/feeds/{feedId}/process/` |
| Delete feed | `DELETE /supplier-feed/feeds/{feedId}/` |

**Polling:** `GET .../feeds/{feedId}/` every **2 s** until status ∈ `{matched, partial, done, error}`.

Lifecycle stages and UI:
| Status | UI |
|--------|----|
| `draft` | Dropzone + file list + Process button |
| `processing` | Spinner + "Processing…" |
| `matched` | Stats: total / matched / skipped + "Трансформировано: N снимков" stat line |
| `partial` | Stats + link to queue page |
| `done` | Completion message + "Трансформировано: N снимков" stat line |
| `error` | Error message + Delete button |

- Snapshot stat (`GET /api/transform/snapshots/?source_feed={feedId}`) shown after `matched`/`done`; confirms transform task fired. Verify `?source_feed` filter exists in API before implementing.

### Feed Queue — `/suppliers/:id/feeds/:feedId/queue`
**File:** `src/features/supplier/pages/FeedQueuePage.tsx`

| Action | Endpoint |
|--------|----------|
| Load supplier | `GET /suppliers/{id}/` |
| List queue entries | `GET /supplier-feed/feeds/{feedId}/queue/` (paginated, 20/page) |
| Confirm candidate | `POST /supplier-feed/feeds/{feedId}/queue/{entryId}/resolve/` `{product_id}` |
| Skip entry | `POST /supplier-feed/feeds/{feedId}/queue/{entryId}/resolve/` `{skipped: true}` |
| Manual product search | `GET /products/products/?q=...` (debounced 300 ms) |

- Entry cards show `supplier_sku` + all `data` key-values, then each `MatchCandidate` (name, sku, category, score badge) with a "Подтвердить" button.
- Per-card actions: "Найти вручную" (opens search modal), "Пропустить".
- Search modal: `TextInput` with ~300 ms debounce → product list → clicking a result calls resolve with `product_id` and closes the modal.
- Resolved entries are removed from the local list immediately on success.
- When the last entry on the last page is resolved, navigates to `/suppliers/{id}/feeds/{feedId}`.
- Invalidates `supplierKeys.queue(feedId, page)` after each resolve.

### Supplier Links — `/suppliers/:id/links`
**File:** `src/features/supplier/pages/SupplierLinksPage.tsx`

Placeholder — no API calls yet.

---

## Transform Feature

No top-level nav entry. All pages reachable contextually (from mapping edit page or via direct link).

### Snapshot Fields — `/transform/snapshot-fields`
**File:** `src/features/transform/pages/SnapshotFieldsPage.tsx`

| Action | Endpoint |
|--------|----------|
| List fields | `GET /api/transform/snapshot-fields/` |
| Create field | `POST /api/transform/snapshot-fields/` |
| Update field | `PATCH /api/transform/snapshot-fields/{id}/` |
| Delete field | `DELETE /api/transform/snapshot-fields/{id}/` |

- Table: `slug`, `name`, `value_type`, `description`. Same shape as `BrandsPage`.
- Inline create/edit modal (4 fields: slug, name, value_type Select, description).
- Delete: 409 = field referenced by a rule → error notification "Поле используется в правилах".
- Invalidates `transformKeys.snapshotFields()` on create/update/delete.

---

## Prices

### `/prices` — PriceTypesPage
File: `src/features/pricing/pages/PriceTypesPage.tsx`

| Action | Endpoint |
|--------|----------|
| List price types | `GET /pricing/price-types/` |
| Create price type | `POST /pricing/price-types/` |
| Update label | `PATCH /pricing/price-types/{id}/` |
| Delete price type | `DELETE /pricing/price-types/{id}/` |

Query keys: `pricingKeys.priceTypes()`

- Table with Ключ (slug, read-only) and Название (label) columns.
- Create modal warns that the key cannot be changed after creation.
- Edit modal allows updating only the label.
- Delete shows a confirmation dialog.

### PricingRulesSection (embedded in `/suppliers/:id`)
File: `src/features/pricing/components/PricingRulesSection.tsx`

| Action | Endpoint |
|--------|----------|
| List rules for supplier | `GET /pricing/rules/?supplier={id}` |
| Create rule | `POST /pricing/rules/` |
| Update rule | `PATCH /pricing/rules/{id}/` |
| Delete rule | `DELETE /pricing/rules/{id}/` |
| List price types (for labels) | `GET /pricing/price-types/` |

Query keys: `pricingKeys.rules(supplierId)`, `pricingKeys.priceTypes()`

- Rule cards show: `source_price_type label → dest_price_type label`, mode badge, priority.
- Modal fields: source/dest price type Selects, mode SegmentedControl (formula/fixed).
- Formula mode: markup % + increase NumberInputs.
- Fixed mode: value NumberInput.
- Optional conditions (Collapse): price_from, price_to, date_from, date_to.
- Invalidates `pricingKeys.rules(supplierId)` on create/update/delete.

---

## Complete Endpoint Index

### Auth
```
GET  /auth/csrf/
POST /auth/login/
GET  /auth/me/
POST /auth/logout/
```

### Dataframe
```
GET    /dataframe/pipelines/
GET    /dataframe/pipelines/{id}/
POST   /dataframe/pipelines/
PUT    /dataframe/pipelines/{id}/
DELETE /dataframe/pipelines/{id}/
POST   /dataframe/sessions/
GET    /dataframe/sessions/{sessionId}/
DELETE /dataframe/sessions/{sessionId}/
POST   /dataframe/preview/
```

### Products
```
GET    /products/products/
GET    /products/products/facets/
GET    /products/products/{id}/
POST   /products/products/
PATCH  /products/products/{id}/
DELETE /products/products/{id}/

GET    /products/categories/
POST   /products/categories/
PATCH  /products/categories/{id}/
DELETE /products/categories/{id}/
POST   /products/categories/{id}/characteristics/            # {char_type_id} or {create:{...}}
DELETE /products/categories/{id}/characteristics/{charId}/
GET    /products/categories/{id}/characteristics/{charId}/usage/
POST   /products/categories/{id}/assign-products/           # {product_ids:[...]}

GET    /products/brands/
POST   /products/brands/
PATCH  /products/brands/{id}/
DELETE /products/brands/{id}/

GET    /products/characteristic-types/           # supports ?name__in=, ?search=, ?categories=, ?value_type=, ?required=, ?page_size=
POST   /products/characteristic-types/
PATCH  /products/characteristic-types/{id}/
DELETE /products/characteristic-types/{id}/
POST   /products/characteristic-types/{id}/rename/preview/
POST   /products/characteristic-types/{id}/rename/commit/
POST   /products/characteristic-types/{id}/retype/preview/
POST   /products/characteristic-types/{id}/retype/commit/
GET    /products/characteristic-types/jobs/{jobId}/   # polling

POST   /products/import/preview/
POST   /products/import/commit/
GET    /products/import/jobs/{jobId}/                 # polling

POST   /products/categories/import/preview/
POST   /products/categories/import/commit/
GET    /products/categories/import/jobs/{jobId}/      # polling
```

### Transform
```
GET    /api/transform/snapshot-fields/
GET    /api/transform/snapshot-fields/{id}/
POST   /api/transform/snapshot-fields/
PATCH  /api/transform/snapshot-fields/{id}/
DELETE /api/transform/snapshot-fields/{id}/

GET    /api/transform/rules/             # ?feed_mapping={id}
GET    /api/transform/rules/{id}/
POST   /api/transform/rules/
PATCH  /api/transform/rules/{id}/
DELETE /api/transform/rules/{id}/

GET    /api/transform/snapshots/         # ?product={id} and/or ?source_feed={id} — verify filters exist
GET    /api/transform/snapshots/{id}/
```

### Suppliers
```
GET    /suppliers/
GET    /suppliers/{id}/
POST   /suppliers/
PATCH  /suppliers/{id}/
DELETE /suppliers/{id}/

GET    /supplier-feed/mappings/          # ?supplier={id}
GET    /supplier-feed/mappings/{id}/
POST   /supplier-feed/mappings/
PATCH  /supplier-feed/mappings/{id}/
DELETE /supplier-feed/mappings/{id}/

GET    /supplier-feed/feeds/             # ?supplier={id}
GET    /supplier-feed/feeds/{feedId}/    # polled every 2 s
POST   /supplier-feed/feeds/
DELETE /supplier-feed/feeds/{feedId}/
POST   /supplier-feed/feeds/{feedId}/upload/
DELETE /supplier-feed/feeds/{feedId}/files/{sessionId}/
POST   /supplier-feed/feeds/{feedId}/process/

GET    /supplier-feed/feeds/{feedId}/queue/                            # paginated, 20/page
POST   /supplier-feed/feeds/{feedId}/queue/{entryId}/resolve/         # {product_id} or {skipped:true}

GET    /supplier-feed/markup-sets/          # ?mapping={id}
GET    /supplier-feed/markup-sets/{id}/
POST   /supplier-feed/markup-sets/
PATCH  /supplier-feed/markup-sets/{id}/
DELETE /supplier-feed/markup-sets/{id}/

GET    /supplier-feed/markup-rules/         # ?markup_set={id}
POST   /supplier-feed/markup-rules/
PATCH  /supplier-feed/markup-rules/{id}/
DELETE /supplier-feed/markup-rules/{id}/
```

### Pricing
```
GET    /pricing/price-types/
POST   /pricing/price-types/
PATCH  /pricing/price-types/{id}/
DELETE /pricing/price-types/{id}/

GET    /pricing/rules/              # ?supplier={id}
POST   /pricing/rules/
PATCH  /pricing/rules/{id}/
DELETE /pricing/rules/{id}/
```

---

## Polling Summary

| Page | Endpoint | Interval | Stop condition |
|------|----------|----------|----------------|
| Product Import | `GET /products/import/jobs/{jobId}/` | 2 s | status ∈ {success, error} |
| Category Import | `GET /products/categories/import/jobs/{jobId}/` | 2 s | status ∈ {success, error} |
| Char Type mutations | `GET /products/characteristic-types/jobs/{jobId}/` | 2 s | status ∈ {success, error} |
| Supplier Feed | `GET /supplier-feed/feeds/{feedId}/` | 2 s | status ∈ {matched, partial, done, error} |

---

## Query Key Map

| Key factory | Invalidated by |
|-------------|----------------|
| `productKeys.all` | product create/update/delete, import commit, char retype/rename |
| `productKeys.list(filters)` | (covered by `.all`) |
| `productKeys.detail(id)` | product update/delete |
| `categoryKeys.all` | category create/delete, category import commit, char-type link add/remove, assign-products |
| `categoryKeys.detail(id)` | char-type link add/remove, assign-products |
| `brandKeys.all` | brand create/delete |
| `charTypeKeys.all` | char type create/delete/edit, rename/retype job success |
| `importJobKeys.detail(jobId)` | polling only |
| `charMutationJobKeys.detail(jobId)` | polling only |
| `dataframeKeys.pipelines()` | pipeline create/update/delete |
| `dataframeKeys.pipeline(id)` | pipeline update (also `.set` on save) |
| `supplierKeys.all` | supplier create/update/delete |
| `supplierKeys.supplier(id)` | supplier update |
| `supplierKeys.mappings(supplierId)` | mapping create/update/delete |
| `supplierKeys.mapping(id)` | mapping update |
| `supplierKeys.feeds(supplierId)` | feed create/delete |
| `supplierKeys.feed(feedId)` | file upload/delete, process, polling |
| `supplierKeys.queue(feedId, page)` | resolve/create/ignore per entry |
| `supplierKeys.markupSets(mappingId)` | markup set create/update/delete, rule batch save |
| `transformKeys.snapshotFields()` | field create/update/delete |
| `transformKeys.snapshotField(id)` | field update |
| `transformKeys.rules(mappingId)` | rule create/update/delete |
| `transformKeys.snapshots(productId)` | read-only (transform task writes via backend) |
| `pricingKeys.priceTypes()` | price type create/update/delete |
| `pricingKeys.rules(supplierId)` | pricing rule create/update/delete |
