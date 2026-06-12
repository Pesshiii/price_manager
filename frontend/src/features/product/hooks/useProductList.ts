import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { listProducts } from '../api';
import { productKeys } from '../queryKeys';
import type { ProductFilters } from '../types';

export function useProductList(filters: ProductFilters) {
  return useQuery({
    queryKey: productKeys.list(filters),
    queryFn: () => listProducts(filters),
    placeholderData: keepPreviousData,
  });
}
