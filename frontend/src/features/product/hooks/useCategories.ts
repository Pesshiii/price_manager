import { useQuery } from '@tanstack/react-query';
import { listCategories } from '../api';
import { categoryKeys } from '../queryKeys';

export function useCategories() {
  return useQuery({
    queryKey: categoryKeys.list(),
    queryFn: () => listCategories(),
    staleTime: 5 * 60_000,
  });
}
