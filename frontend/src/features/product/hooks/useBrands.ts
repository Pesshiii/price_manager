import { useQuery } from '@tanstack/react-query';
import { listBrands } from '../api';
import { brandKeys } from '../queryKeys';

export function useBrands() {
  return useQuery({
    queryKey: brandKeys.list(),
    queryFn: () => listBrands(),
    staleTime: 5 * 60_000,
  });
}
