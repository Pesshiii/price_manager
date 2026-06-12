import type { ProductFilters } from './types';

export const productKeys = {
  all: ['products'] as const,
  lists: () => [...productKeys.all, 'list'] as const,
  list: (filters: ProductFilters) => [...productKeys.lists(), filters] as const,
  facets: (filters: ProductFilters) => [...productKeys.all, 'facets', filters] as const,
  detail: (id: number) => [...productKeys.all, 'detail', id] as const,
};

export const categoryKeys = {
  all: ['categories'] as const,
  list: () => [...categoryKeys.all, 'list'] as const,
  detail: (id: number) => [...categoryKeys.all, 'detail', id] as const,
};

export const brandKeys = {
  all: ['brands'] as const,
  list: () => [...brandKeys.all, 'list'] as const,
  detail: (id: number) => [...brandKeys.all, 'detail', id] as const,
};

export const charTypeKeys = {
  all: ['characteristic-types'] as const,
  list: (params?: Record<string, unknown>) =>
    [...charTypeKeys.all, 'list', params ?? {}] as const,
  detail: (id: number) => [...charTypeKeys.all, 'detail', id] as const,
};

export const importJobKeys = {
  all: ['import-jobs'] as const,
  detail: (id: string | null) => [...importJobKeys.all, 'detail', id] as const,
};

export const charMutationJobKeys = {
  all: ['char-mutation-jobs'] as const,
  detail: (id: string | null) =>
    [...charMutationJobKeys.all, 'detail', id] as const,
};

export const categoryImportJobKeys = {
  detail: (id: string | null) => ['product', 'category-import-jobs', id] as const,
};
