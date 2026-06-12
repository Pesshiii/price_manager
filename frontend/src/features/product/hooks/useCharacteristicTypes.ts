import { useQuery } from '@tanstack/react-query';
import { listCharacteristicTypes, type ListCharTypesParams } from '../api';
import { charTypeKeys } from '../queryKeys';

/**
 * Fetches one page of CharacteristicType. After EAV-style import the table can
 * easily hold thousands of rows, so callers should either:
 *   - work with the paginated subset (`data?.results`), or
 *   - pass an explicit `search` to narrow it (autocomplete-style picker), or
 *   - pass `page_size: 2000` only on dedicated admin pages.
 *
 * Consumers should always read `data?.results ?? []` — never `data` directly.
 */
export function useCharacteristicTypes(params: ListCharTypesParams = {}) {
  // Avoid the unbounded fetch — only run when the caller scoped the query
  // (search/name__in/category) or explicitly opted into the full page.
  const hasScope =
    !!params.search ||
    !!(params.name__in && params.name__in.length > 0) ||
    params.category !== undefined ||
    params.page_size !== undefined ||
    params.page !== undefined;
  return useQuery({
    queryKey: charTypeKeys.list(params as unknown as Record<string, unknown>),
    queryFn: () => listCharacteristicTypes(params),
    staleTime: 5 * 60_000,
    enabled: hasScope,
  });
}
