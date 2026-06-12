# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Package manager is **pnpm** (pinned via `packageManager` field in `package.json`). Node 18+.

- `pnpm dev` — Vite dev server on `http://localhost:5173`. Proxies `/api/*` to `VITE_PROXY_TARGET` (default `http://localhost:8000`, Django backend).
- `pnpm build` — runs `tsc --noEmit` then `vite build`.
- `pnpm typecheck` — `tsc --noEmit` only.
- `pnpm test` — `vitest run` (jsdom + MSW).
- `pnpm test:watch` — Vitest in watch mode.
- Single test: `pnpm test <path-substring>` or `pnpm test -t "<test name>"`.

## Architecture

### Provider chain (`src/main.tsx`)
`MantineProvider` → `Notifications` → `QueryClientProvider` → `AuthProvider` → `RouterProvider`. React Query is configured with `retry: false`, `refetchOnWindowFocus: false`, `staleTime: 30_000`.

### Routing (`src/routes.tsx`)
React Router v6 `createBrowserRouter`. The root path is wrapped in `RequireAuth` + `AppLayout`; `/login` is public; unknown paths redirect to `/`. Feature pages are imported from `src/features/<feature>/pages/`. Routes `/suppliers` and `/prices` are placeholder pages (not yet implemented).

### Auth + HTTP (`src/api/client.ts`, `src/api/auth.ts`, `src/auth/`)
- Backend is Django with session cookies + CSRF. The shared axios instance uses `withCredentials: true` and copies the `csrftoken` cookie into the `X-CSRFToken` header for non-safe methods. Do not remove this — it will silently break writes.
- A 401 response on any non-`/auth/*` request triggers `window.location.assign('/login')`. When writing tests, ensure MSW handlers return non-401 for non-auth routes (or mock `window.location`).
- Auth endpoints: `/auth/csrf/`, `/auth/login/`, `/auth/me/`, `/auth/logout/`. `AuthContext` resolves the current user on mount via `getCurrentUser()`.

### Path alias
`@/*` → `src/*` (configured in both `vite.config.ts` and `tsconfig.json`). Prefer the alias over relative imports across feature boundaries.

### Feature layout
`src/features/<name>/{api.ts, queryKeys.ts, types.ts, components/, hooks/, pages/, __tests__/}`. Server state lives in react-query — there is no global client store. Each feature owns its query keys as exported factory objects (e.g. `productKeys`, `categoryKeys`, `charTypeKeys` in `features/product/queryKeys.ts`). Current features:
- **dataframe** — pipeline registry + editor + preview. Upload-session workflow: `POST /dataframe/sessions/` returns a `session_id`, then `POST /dataframe/preview/` runs `instructions` against that session. The preview table headers double as a "column actions" entry point — see "Column-aware transform menu" below.
- **product** — product catalog with faceted filter, CRUD, characteristic-type admin with safe JSONB mutations, and import via dataframe pipeline.

## API map
### Endpoints

**ALWAYS** consult `../API_MAP.md` treat it as the single source of true api

### Characteristic type CRUD + safe mutation flow

`CharacteristicTypesPage.tsx` is the admin surface. It has a filter toolbar (search, category MultiSelect, value_type Select, required SegmentedControl) with debounced search (~300ms). The list fetches with `page_size: 2000` to get all types in one request.

**Edit flow** (`CharacteristicTypeEditModal.tsx`): editable fields are split into two groups:
- *Safe* (`label`, `unit`, `options`, `required`, `categories`) — submitted via plain `PATCH`.
- *Migrating* (`name`, `value_type`) — detected as changed and routed through a wizard **after** saving safe fields. Rename always runs before retype (retype scans by the new key name).

**Retype wizard** (`CharacteristicRetypeWizard.tsx`): calls `previewRetype` → if `invalid_count === 0`, commits immediately; otherwise shows conflict modal. If `unique_invalid.length < SMALL_INVALID_THRESHOLD` (10), shows per-value override table; otherwise shows single fallback Select. Submits `{new_value_type, fallback, default_value?, value_map?}` to `commitRetype`. Keys in `value_map` MUST match `unique_invalid[i].value` verbatim.

**Rename wizard** (`CharacteristicRenameWizard.tsx`): calls `previewRename` → if `collision_count === 0`, commits with `on_conflict: 'overwrite'`; otherwise shows collision list + `on_conflict` SegmentedControl.

**Polling** (`useCharMutationJob` in `hooks/useCharMutations.ts`): `useQuery` with `refetchInterval: 2000`, stops when `status ∈ {'success', 'error'}`. On terminal success, `useCharMutationInvalidation` invalidates both `charTypeKeys.all` and `productKeys.all` (retype/rename rewrites every product's JSONB + facet cache).

### Import flow (two-step wizard, async)

The wizard at `ImportPage.tsx` has **two** steps + a results pane:

1. **Источник** — upload (`POST /dataframe/sessions/` → `session_id`) and pick either a saved pipeline or build one ad-hoc.
2. **Маппинг** — collect a `mapping` object where each Product field / CharacteristicType is bound to a dataframe column (or a constant). Uses `useCharacteristicTypes()` with no params (global list). Users can create new types inline via a modal; the backend re-attaches the M2M on commit. Below the static list, users can press **«Добавить вариант»** to add dynamic EAV rows.
   ```ts
   type FieldMapping = { column: string } | { const: unknown };
   interface DynamicCharSpec {
     name_column: string;
     value_column: string;
     unit_column?: string;
   }
   interface ImportMapping {
     sku?: FieldMapping;
     name?: FieldMapping;
     category?: CategoryFieldMapping; // { column, path_separator? } — path_separator enables get_or_create chain
     brand?: FieldMapping;
     description?: FieldMapping;
     status?: FieldMapping;
     characteristics?: Record<string, FieldMapping>; // keyed by CharacteristicType.name
     dynamic_characteristics?: DynamicCharSpec[];
   }
   ```
3. **Импорт** — preview, then commit. Both return an `ImportJob` with `status: 'pending'`; the page polls `GET /products/import/jobs/<id>/` every 2s via `useImportJob(jobId)` until terminal status.

**Notification dedup**: effects guarded by `handledPreviewRef` / `handledCommitRef` keyed by `${job.id}:${status}` — fires exactly once per (job, terminal status). Reset both refs in `resetDownstream`/`cleanupSession` when starting a new flow.

**Persistence** (`persistence.ts`): full wizard state is stored in `localStorage` under `STORAGE_KEY = 'product-import-state-v2'` as `ImportPersistedState` (version 2 schema). An F5 mid-commit resumes polling automatically. `loadPersistedState()` returns `null` if version mismatches and clears the stale entry.

### Implementation notes for `src/features/product/`

- **api.ts** — thin wrappers around the shared `api` axios instance, `const BASE = '/products'`. List endpoint returns `Paginated<Product>`; categories/brands list endpoints fetch with default `page_size=500`. `listCharacteristicTypes` accepts `ListCharTypesParams` including `name__in` for bulk metadata fetch.
- **queryKeys.ts** — factory objects: `productKeys`, `categoryKeys`, `brandKeys`, `charTypeKeys`, `importJobKeys`, `charMutationJobKeys`. Cache invalidation after commit targets `productKeys.all` + `categoryKeys.all` + `brandKeys.all`. After retype/rename, `charTypeKeys.all` + `productKeys.all`.
- **types.ts** — `value_type` union mirrors backend choices. `SMALL_INVALID_THRESHOLD = 10` is the cutoff for per-value vs. fallback-only conflict UI. `ImportPersistedState` schema lives in `persistence.ts`, not `types.ts`.
- **Filter UI** — sidebar facets call `/products/products/facets/` with the **same** filter params as the list. `char__<name>` is repeatable: multiple values yield OR.
- **Pagination** — DRF `PageNumberPagination` with `?page=N&page_size=N`. Use `count` from response for total.
- **CSRF / 401** — handled by the existing axios interceptor; no special-casing needed.
- **MSW handlers** — tests must mock product endpoints; `onUnhandledRequest: 'error'` will fail otherwise.

### Dynamic (EAV) characteristics

Each `DynamicCharSpec` is `{name_column, value_column, unit_column?}`. The backend `commit_rows` does `slugify(name, allow_unicode=True)` + `get_or_create` on the resulting `CharacteristicType`, writes the value into `Product.characteristics[slug]`, and uses `unit_column` for `CharacteristicType.unit` only when the type's unit is empty ("first-write wins"). Static `mapping.characteristics` takes precedence on slug collisions.

The "Проверить" button on the mapping step is disabled if any dynamic group has only one of `name_column` / `value_column` set — `ImportPage.tsx:dynamicGroupsValid` checks `Boolean(name) === Boolean(value)` for every spec.

### Column-aware transform menu

`PreviewTable.tsx` renders each column header inside a Mantine `<Menu>` whose items come from `columnTransforms` (a filtered subset of the registry). `DataframeBuilder.tsx` does the filtering: any `TransformSpec` whose `args` include at least one `ArgSpec` with `type === 'column' | 'columns'` is column-aware. Picking an item calls `onColumnAction(column, transformName)`, which appends a new step with the clicked column already filled in and selects the new step. No hardcoded transform list — stays in sync with the backend registry automatically.

### Tests
Vitest + jsdom + Testing Library + MSW. `src/test/setup.ts` polyfills `matchMedia` and `ResizeObserver` (needed by Mantine), and starts the MSW server with `onUnhandledRequest: 'error'` — any unmocked request fails the test. Use the helper at `src/test/renderWithProviders.tsx` to wrap components with the provider stack.

## Conventions

- Mantine 7 sub-package styles are imported in `main.tsx` (`@mantine/core`, `@mantine/notifications`, `@mantine/dropzone`). Adding a new Mantine sub-package requires importing its CSS there too.
- UI strings are in Russian (see route placeholders in `src/routes.tsx`).
- Every time new page or feature is added **ALWAYS** update the `FRONTEND_MAP.md` file

## Agent skills

### Issue tracker

Issues live in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
