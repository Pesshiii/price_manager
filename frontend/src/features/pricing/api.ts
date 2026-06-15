import { api } from '@/api/client';
import type { PriceType } from './types';

const BASE = '/pricing';

export async function listPriceTypes(): Promise<PriceType[]> {
  const { data } = await api.get<{ results: PriceType[]; count: number }>(
    `${BASE}/price-types/`,
    { params: { page_size: 1000 } },
  );
  if (data.count > data.results.length) {
    console.warn(
      `listPriceTypes: received ${data.results.length} of ${data.count} price types. ` +
        'Some types are not shown. Increase page_size or implement pagination.',
    );
  }
  return data.results;
}
