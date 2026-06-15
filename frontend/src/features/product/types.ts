export type ValueType = 'string' | 'integer' | 'float' | 'boolean' | 'choice';

export type ProductStatus = string;

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Category {
  id: number;
  name: string;
  slug: string;
  parent: number | null;
  level: number;
}

export interface Brand {
  id: number;
  name: string;
  slug: string;
}

export interface CategoryRef {
  id: number;
  name: string;
  level: number;
}

export interface CharacteristicType {
  id: number;
  name: string;
  label: string;
  value_type: ValueType;
  options: string[];
  unit: string;
  required: boolean;
  categories: number[];
  /** Read-only sibling of `categories` — names + MPTT level for the detail modal. */
  categories_detail?: CategoryRef[];
}

// ---- Safe-mutation (retype / rename) types --------------------------------

export type Fallback = 'drop' | 'null' | 'default';
export type RenameConflict = 'overwrite' | 'keep_existing' | 'skip_row';

export interface RetypePreviewResponse {
  total_with_key: number;
  invalid_count: number;
  /** Unique raw values that won't coerce, capped at 200 (see `truncated`). */
  unique_invalid: Array<{ value: string; count: number }>;
  truncated: boolean;
}

export interface RetypeCommitPayload {
  new_value_type: ValueType;
  fallback: Fallback;
  /** Required only when `fallback === 'default'`. */
  default_value?: unknown;
  /**
   * Per-raw-value overrides. Keys MUST match the strings in `unique_invalid[i].value`
   * verbatim — the backend keys conflicts by `str(raw)` (`'true'`/`'false'` for booleans).
   */
  value_map?: Record<string, unknown>;
}

export interface RenamePreviewResponse {
  total_to_rename: number;
  collision_count: number;
  /** Products that already carry both keys, capped at 100. */
  collisions: Array<{ product_id: number; sku: string }>;
}

export interface RenameCommitPayload {
  new_name: string;
  on_conflict: RenameConflict;
}

export type CharMutationJobKind = 'retype' | 'rename';
export type CharMutationJobStatus = 'pending' | 'running' | 'success' | 'error';

export interface CharMutationJob {
  id: string;
  kind: CharMutationJobKind;
  status: CharMutationJobStatus;
  /** Short Russian sentence describing the current worker step (empty after terminal). */
  stage: string;
  char_type: number;
  payload: Record<string, unknown>;
  result: Record<string, number> | null;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** Threshold below which the retype wizard renders a per-value override table
 *  instead of a single fallback. Mirrors the backend constant of the same name. */
export const SMALL_INVALID_THRESHOLD = 10;

export type CharacteristicValue = string | number | boolean;

export interface Product {
  id: number;
  sku: string;
  name: string;
  category: number | null;
  brand: number | null;
  description: string;
  status: ProductStatus;
  characteristics: Record<string, CharacteristicValue>;
  image_urls: string[];
  created_at: string;
  updated_at: string;
  prices?: Record<string, number | null>;
}

export interface ProductWritePayload {
  sku: string;
  name: string;
  category?: number | null;
  brand?: number | null;
  description?: string;
  status?: ProductStatus;
  characteristics: Record<string, CharacteristicValue>;
  image_urls: string[];
}

export interface ProductFilters {
  q?: string;
  category?: number;
  brand?: number;
  status?: string;
  chars: Record<string, string[]>;
  page: number;
  pageSize: number;
  price_type?: string;
  price_min?: number;
  price_max?: number;
  price_types?: string[];
}

export const DEFAULT_PAGE_SIZE = 50;

export const emptyFilters = (): ProductFilters => ({
  chars: {},
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
});

export interface FacetBucket {
  value: unknown;
  count: number;
}

export interface FacetGroupData {
  label: string;
  unit: string;
  value_type: ValueType;
  buckets: FacetBucket[];
}

export type FacetsResponse = Record<string, FacetGroupData>;

export type FieldMapping = { column: string } | { const: unknown };

export const PRODUCT_STATUS_OPTIONS = [
  { value: 'draft', label: 'Черновик' },
  { value: 'active', label: 'Активный' },
  { value: 'archived', label: 'В архиве' },
] as const;

export type ProductStatusValue = 'draft' | 'active' | 'archived';

export type CategoryFieldMapping =
  | { column: string; path_separator?: string }
  | { const: unknown };

/**
 * EAV-style "dynamic" characteristic mapping: name/value/unit each bound to
 * a source column. Per row the worker reads those cells, slugifies the name
 * and auto-creates the CharacteristicType. The unit_column is optional.
 */
export interface DynamicCharSpec {
  name_column: string;
  value_column: string;
  unit_column?: string;
}

export interface ImportMapping {
  sku?: FieldMapping;
  name?: FieldMapping;
  category?: CategoryFieldMapping;
  brand?: FieldMapping;
  description?: FieldMapping;
  status?: FieldMapping;
  characteristics?: Record<string, FieldMapping>;
  dynamic_characteristics?: DynamicCharSpec[];
  default_status?: ProductStatusValue;
}

/**
 * Backend може отдавать ошибки строки в разных формах:
 *  - массив строк: ["sku: required"]
 *  - объект DRF-стиля: { sku: ["required"], characteristics: ["color: ..."] }
 *  - строка или null
 * Нормализация — в normalizeRowErrors() (см. ImportPreviewResults).
 */
export type ImportRowErrors =
  | string[]
  | Record<string, string | string[]>
  | string
  | null
  | undefined;

export interface ImportPreviewRow {
  index: number;
  payload: Record<string, unknown>;
  errors: ImportRowErrors;
}

export interface ImportPreviewResult {
  rows: ImportPreviewRow[];
  total: number;
  returned: number;
  valid: number;
  invalid: number;
}

export interface ImportCommitResult {
  created: number;
  updated: number;
  skipped: number;
  errors: Array<{ index: number; message: string }>;
}

export interface ImportRequestBody {
  session_id: string;
  instructions: unknown;
  mapping: ImportMapping;
  row_limit?: number;
  default_status?: ProductStatusValue;
}

export interface CategoryImportMapping {
  path_column: string;
  separator?: string;
}

export interface CategoryImportRequestBody {
  session_id: string;
  instructions: unknown;
  mapping: CategoryImportMapping;
  row_limit?: number;
}

export type CategoryRowStatus = 'new' | 'exists' | 'invalid';

export interface CategoryImportPreviewRow {
  index: number;
  path: string;
  segments: string[];
  status: CategoryRowStatus;
  error?: string;
}

export interface CategoryImportPreviewResult {
  rows: CategoryImportPreviewRow[];
  total: number;
  returned: number;
  new: number;
  exists: number;
  invalid: number;
}

export interface CategoryImportCommitResult {
  created: number;
  skipped: number;
  invalid: number;
  errors: Array<{ index: number; path: string; error: string }>;
}

export type ImportJobStatus = 'pending' | 'running' | 'success' | 'error';

export type ImportJobKind = 'preview' | 'commit';

export interface ImportJob {
  id: string;
  kind: ImportJobKind;
  status: ImportJobStatus;
  stage: string;
  result: ImportPreviewResult | ImportCommitResult | null;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}
