import { api } from '@/api/client';
import type { Paginated } from '@/features/product/types';
import type {
  BulkCreateProductsResult,
  FeedMapping,
  FeedMappingWritePayload,
  FeedMarkupRule,
  FeedMarkupRuleWritePayload,
  FeedMarkupSet,
  FeedMarkupSetWritePayload,
  ProductSearchResult,
  Supplier,
  SupplierFeed,
  SupplierFeedDetail,
  SupplierFeedEntry,
  SupplierFeedWritePayload,
  SupplierWritePayload,
  UploadedFile,
} from './types';

const BASE = '/suppliers';
const MAPPINGS_BASE = '/supplier-feed/mappings';
const FEEDS_BASE = '/supplier-feed/feeds';
const MARKUP_SETS_BASE = '/supplier-feed/markup-sets';
const MARKUP_RULES_BASE = '/supplier-feed/markup-rules';

export async function listSuppliers(): Promise<Supplier[]> {
  const { data } = await api.get<Supplier[]>(`${BASE}/`);
  return data;
}

export async function getSupplier(id: number): Promise<Supplier> {
  const { data } = await api.get<Supplier>(`${BASE}/${id}/`);
  return data;
}

export async function createSupplier(payload: SupplierWritePayload): Promise<Supplier> {
  const { data } = await api.post<Supplier>(`${BASE}/`, payload);
  return data;
}

export async function updateSupplier(id: number, payload: SupplierWritePayload): Promise<Supplier> {
  const { data } = await api.patch<Supplier>(`${BASE}/${id}/`, payload);
  return data;
}

export async function deleteSupplier(id: number): Promise<void> {
  await api.delete(`${BASE}/${id}/`);
}

export async function listFeedMappings(supplierId: number): Promise<FeedMapping[]> {
  const { data } = await api.get<FeedMapping[]>(`${MAPPINGS_BASE}/`, {
    params: { supplier: supplierId },
  });
  return data;
}

export async function getFeedMapping(id: number): Promise<FeedMapping> {
  const { data } = await api.get<FeedMapping>(`${MAPPINGS_BASE}/${id}/`);
  return data;
}

export async function createFeedMapping(payload: FeedMappingWritePayload): Promise<FeedMapping> {
  const { data } = await api.post<FeedMapping>(`${MAPPINGS_BASE}/`, payload);
  return data;
}

export async function updateFeedMapping(
  id: number,
  payload: Partial<FeedMappingWritePayload>,
): Promise<FeedMapping> {
  const { data } = await api.patch<FeedMapping>(`${MAPPINGS_BASE}/${id}/`, payload);
  return data;
}

export async function deleteFeedMapping(id: number): Promise<void> {
  await api.delete(`${MAPPINGS_BASE}/${id}/`);
}

export async function listFeeds(supplierId: number): Promise<SupplierFeed[]> {
  const { data } = await api.get<SupplierFeed[]>(`${FEEDS_BASE}/`, {
    params: { supplier: supplierId },
  });
  return data;
}

export async function createFeed(payload: SupplierFeedWritePayload): Promise<SupplierFeed> {
  const { data } = await api.post<SupplierFeed>(`${FEEDS_BASE}/`, payload);
  return data;
}

export async function getFeed(feedId: number): Promise<SupplierFeedDetail> {
  const { data } = await api.get<SupplierFeedDetail>(`${FEEDS_BASE}/${feedId}/`);
  return data;
}

export async function uploadFile(feedId: number, file: File): Promise<UploadedFile> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post<UploadedFile>(`${FEEDS_BASE}/${feedId}/upload/`, form);
  return data;
}

export async function deleteFile(feedId: number, sessionId: string): Promise<void> {
  await api.delete(`${FEEDS_BASE}/${feedId}/files/${sessionId}/`);
}

export async function processFeed(feedId: number): Promise<SupplierFeedDetail> {
  const { data } = await api.post<SupplierFeedDetail>(`${FEEDS_BASE}/${feedId}/process/`);
  return data;
}

export async function deleteFeed(feedId: number): Promise<void> {
  await api.delete(`${FEEDS_BASE}/${feedId}/`);
}

export async function listQueueEntries(
  feedId: number,
  page = 1,
): Promise<Paginated<SupplierFeedEntry>> {
  const { data } = await api.get<Paginated<SupplierFeedEntry>>(`${FEEDS_BASE}/${feedId}/queue/`, {
    params: { page },
  });
  return data;
}

export async function resolveEntry(
  feedId: number,
  entryId: number,
  payload: { product_id: number } | { skipped: true },
): Promise<SupplierFeedEntry> {
  const { data } = await api.post<SupplierFeedEntry>(
    `${FEEDS_BASE}/${feedId}/queue/${entryId}/resolve/`,
    payload,
  );
  return data;
}

export async function searchProductsForQueue(q: string): Promise<Paginated<ProductSearchResult>> {
  const { data } = await api.get<Paginated<ProductSearchResult>>('/products/products/', {
    params: { q },
  });
  return data;
}

export async function createProductFromEntry(
  feedId: number,
  entryId: number,
  payload: { sku: string; name: string },
): Promise<SupplierFeedEntry> {
  const { data } = await api.post<SupplierFeedEntry>(
    `${FEEDS_BASE}/${feedId}/queue/${entryId}/create-product/`,
    payload,
  );
  return data;
}

export async function ignoreEntry(
  feedId: number,
  entryId: number,
): Promise<SupplierFeedEntry> {
  const { data } = await api.post<SupplierFeedEntry>(
    `${FEEDS_BASE}/${feedId}/queue/${entryId}/ignore/`,
    {},
  );
  return data;
}

export async function bulkCreateProducts(
  feedId: number,
  nameColumn: string,
): Promise<BulkCreateProductsResult> {
  const { data } = await api.post<BulkCreateProductsResult>(
    `${FEEDS_BASE}/${feedId}/queue/bulk-create-products/`,
    { name_column: nameColumn },
  );
  return data;
}

export async function listMarkupSets(mappingId: number): Promise<FeedMarkupSet[]> {
  const { data } = await api.get<FeedMarkupSet[]>(`${MARKUP_SETS_BASE}/`, {
    params: { mapping: mappingId },
  });
  return data;
}

export async function createMarkupSet(payload: FeedMarkupSetWritePayload): Promise<FeedMarkupSet> {
  const { data } = await api.post<FeedMarkupSet>(`${MARKUP_SETS_BASE}/`, payload);
  return data;
}

export async function updateMarkupSet(
  id: number,
  payload: Partial<FeedMarkupSetWritePayload>,
): Promise<FeedMarkupSet> {
  const { data } = await api.patch<FeedMarkupSet>(`${MARKUP_SETS_BASE}/${id}/`, payload);
  return data;
}

export async function deleteMarkupSet(id: number): Promise<void> {
  await api.delete(`${MARKUP_SETS_BASE}/${id}/`);
}

export async function createMarkupRule(payload: FeedMarkupRuleWritePayload): Promise<FeedMarkupRule> {
  const { data } = await api.post<FeedMarkupRule>(`${MARKUP_RULES_BASE}/`, payload);
  return data;
}

export async function updateMarkupRule(
  id: number,
  payload: Partial<Omit<FeedMarkupRuleWritePayload, 'markup_set'>>,
): Promise<FeedMarkupRule> {
  const { data } = await api.patch<FeedMarkupRule>(`${MARKUP_RULES_BASE}/${id}/`, payload);
  return data;
}

export async function deleteMarkupRule(id: number): Promise<void> {
  await api.delete(`${MARKUP_RULES_BASE}/${id}/`);
}
