import { api } from '@/api/client';
import type { PriceType, PriceTypeWritePayload, PricingRule, PricingRuleWritePayload } from './types';

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

export async function createPriceType(payload: PriceTypeWritePayload): Promise<PriceType> {
  const { data } = await api.post<PriceType>(`${BASE}/price-types/`, payload);
  return data;
}

export async function updatePriceType(id: number, payload: Partial<PriceTypeWritePayload>): Promise<PriceType> {
  const { data } = await api.patch<PriceType>(`${BASE}/price-types/${id}/`, payload);
  return data;
}

export async function deletePriceType(id: number): Promise<void> {
  await api.delete(`${BASE}/price-types/${id}/`);
}

export async function listPricingRules(supplierId: number): Promise<PricingRule[]> {
  const { data } = await api.get<PricingRule[]>(`${BASE}/rules/`, {
    params: { supplier: supplierId },
  });
  return data;
}

export async function createPricingRule(payload: PricingRuleWritePayload): Promise<PricingRule> {
  const { data } = await api.post<PricingRule>(`${BASE}/rules/`, payload);
  return data;
}

export async function updatePricingRule(id: number, payload: Partial<PricingRuleWritePayload>): Promise<PricingRule> {
  const { data } = await api.patch<PricingRule>(`${BASE}/rules/${id}/`, payload);
  return data;
}

export async function deletePricingRule(id: number): Promise<void> {
  await api.delete(`${BASE}/rules/${id}/`);
}
