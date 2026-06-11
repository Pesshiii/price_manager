import { useQuery } from '@tanstack/react-query';
import { getRegistry } from '../api';
import { dataframeKeys } from '../queryKeys';

export function useDataframeRegistry() {
  return useQuery({
    queryKey: dataframeKeys.registry(),
    queryFn: getRegistry,
    staleTime: 5 * 60_000,
  });
}
