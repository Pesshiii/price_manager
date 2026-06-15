import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { DEFAULT_PAGE_SIZE, type ProductFilters } from '../types';

const CHAR_PREFIX = 'char__';

function parseFilters(searchParams: URLSearchParams): ProductFilters {
  const chars: Record<string, string[]> = {};
  for (const [key, value] of searchParams.entries()) {
    if (key.startsWith(CHAR_PREFIX)) {
      const name = key.slice(CHAR_PREFIX.length);
      if (!chars[name]) chars[name] = [];
      chars[name].push(value);
    }
  }
  const page = Number(searchParams.get('page') ?? '1');
  const pageSize = Number(searchParams.get('page_size') ?? DEFAULT_PAGE_SIZE);
  const filters: ProductFilters = {
    chars,
    page: Number.isFinite(page) && page > 0 ? page : 1,
    pageSize: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : DEFAULT_PAGE_SIZE,
  };
  const q = searchParams.get('q');
  if (q) filters.q = q;
  const category = searchParams.get('category');
  if (category) filters.category = Number(category);
  const brand = searchParams.get('brand');
  if (brand) filters.brand = Number(brand);
  const status = searchParams.get('status');
  if (status) filters.status = status;
  const price_type = searchParams.get('price_type');
  if (price_type) filters.price_type = price_type;
  const price_min = searchParams.get('price_min');
  if (price_min) filters.price_min = Number(price_min);
  const price_max = searchParams.get('price_max');
  if (price_max) filters.price_max = Number(price_max);
  return filters;
}

function serializeFilters(filters: ProductFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (filters.category !== undefined) params.set('category', String(filters.category));
  if (filters.brand !== undefined) params.set('brand', String(filters.brand));
  if (filters.status) params.set('status', filters.status);
  if (filters.page !== 1) params.set('page', String(filters.page));
  if (filters.pageSize !== DEFAULT_PAGE_SIZE) {
    params.set('page_size', String(filters.pageSize));
  }
  for (const [name, values] of Object.entries(filters.chars)) {
    for (const value of values) {
      params.append(`${CHAR_PREFIX}${name}`, value);
    }
  }
  if (filters.price_type) params.set('price_type', filters.price_type);
  if (filters.price_min !== undefined) params.set('price_min', String(filters.price_min));
  if (filters.price_max !== undefined) params.set('price_max', String(filters.price_max));
  return params;
}

export interface UseProductFiltersResult {
  filters: ProductFilters;
  setFilters: (next: ProductFilters) => void;
  patchFilters: (patch: Partial<ProductFilters>) => void;
  toggleCharValue: (name: string, value: string) => void;
  resetFilters: () => void;
}

export function useProductFiltersFromUrl(): UseProductFiltersResult {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);

  const setFilters = useCallback(
    (next: ProductFilters) => setSearchParams(serializeFilters(next)),
    [setSearchParams],
  );

  const patchFilters = useCallback(
    (patch: Partial<ProductFilters>) => {
      const next: ProductFilters = { ...filters, ...patch };
      const resetsPage =
        patch.q !== undefined ||
        patch.category !== undefined ||
        patch.brand !== undefined ||
        patch.status !== undefined ||
        patch.chars !== undefined ||
        patch.price_type !== undefined ||
        patch.price_min !== undefined ||
        patch.price_max !== undefined;
      if (resetsPage && patch.page === undefined) next.page = 1;
      setFilters(next);
    },
    [filters, setFilters],
  );

  const toggleCharValue = useCallback(
    (name: string, value: string) => {
      const current = filters.chars[name] ?? [];
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value];
      const chars = { ...filters.chars };
      if (next.length === 0) {
        delete chars[name];
      } else {
        chars[name] = next;
      }
      patchFilters({ chars });
    },
    [filters.chars, patchFilters],
  );

  const resetFilters = useCallback(() => setSearchParams(new URLSearchParams()), [
    setSearchParams,
  ]);

  return { filters, setFilters, patchFilters, toggleCharValue, resetFilters };
}
