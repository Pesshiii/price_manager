import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { getProductFacets } from '../api';
import { productKeys } from '../queryKeys';
import type { ProductFilters } from '../types';

export function useProductFacets(filters: ProductFilters) {
  return useQuery({
    queryKey: productKeys.facets(filters),
    queryFn: () => getProductFacets(filters),
    placeholderData: keepPreviousData,
  });
}
