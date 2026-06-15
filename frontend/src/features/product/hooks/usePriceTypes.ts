import { useQuery } from '@tanstack/react-query';
import { listPriceTypes } from '@/features/pricing/api';
import { pricingKeys } from '@/features/pricing/queryKeys';

export function usePriceTypes() {
  return useQuery({
    queryKey: pricingKeys.priceTypes(),
    queryFn: listPriceTypes,
    staleTime: 5 * 60_000,
  });
}
