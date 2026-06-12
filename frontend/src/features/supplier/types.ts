export interface Supplier {
  id: number;
  name: string;
}

export interface SupplierWritePayload {
  name: string;
}

export interface FeedMapping {
  id: number;
  supplier: number;
  name: string;
  dataframe: number;
  dataframe_detail: { id: number; name: string };
  supplier_sku_column: string;
  identity_columns: string[];
  variable_columns: string[];
  auto_match_threshold: number;
  product_name_column: string | null;
  product_sku_column: string | null;
}

export interface FeedMappingWritePayload {
  supplier: number;
  name: string;
  dataframe: number;
  supplier_sku_column: string;
  identity_columns: string[];
  variable_columns: string[];
  auto_match_threshold: number;
}

export type SupplierFeedStatus = 'draft' | 'processing' | 'matched' | 'partial' | 'done' | 'error';

export interface SupplierFeed {
  id: number;
  supplier: number;
  feed_mapping: number;
  status: SupplierFeedStatus;
  session_ids: string[];
  error: string | null;
  created_at: string;
}

export interface SupplierFeedWritePayload {
  supplier: number;
  feed_mapping: number;
}

export interface SupplierFeedDetail extends SupplierFeed {
  total: number;
  matched: number;
  queued: number;
  skipped: number;
}

export interface UploadedFile {
  session_id: string;
  filename: string;
  size: number;
  uploaded_at: string;
}

export interface ProductSearchResult {
  id: number;
  name: string;
  sku: string;
}

export interface MatchCandidate {
  product_id: number;
  score: number;
  name: string;
  sku: string;
  category: string;
  brand: string;
}

export interface SupplierFeedEntry {
  id: number;
  supplier_sku: string;
  data: Record<string, unknown>;
  match_candidates: MatchCandidate[];
  best_score: number | null;
}

export interface BulkCreateProductsResult {
  created: number;
  failed: number;
  errors: { entry_id: number; reason: string }[];
}

export interface FeedColumnMapping {
  id: number;
  feed_mapping: number;
  column_name: string;
  role: 'price' | 'stock' | 'other';
  price_type: number | null;
}

export interface FeedColumnMappingWritePayload {
  feed_mapping: number;
  column_name: string;
  role: 'price' | 'stock' | 'other';
  price_type: number | null;
}
