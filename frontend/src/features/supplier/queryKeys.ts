export const supplierKeys = {
  all: ['suppliers'] as const,
  supplier: (id: number) => ['suppliers', id] as const,
  mappings: (supplierId: number) => ['suppliers', supplierId, 'mappings'] as const,
  mapping: (id: number) => ['feed-mappings', id] as const,
  feeds: (supplierId: number) => ['suppliers', supplierId, 'feeds'] as const,
  feed: (feedId: number) => ['supplier-feeds', feedId] as const,
  queue: (feedId: number, page: number) => ['supplier-feeds', feedId, 'queue', page] as const,
  markupSets: (mappingId: number) => ['feed-mappings', mappingId, 'markup-sets'] as const,
};
