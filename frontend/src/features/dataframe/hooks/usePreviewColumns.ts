import { useQuery } from '@tanstack/react-query';
import { previewPipeline } from '../api';
import { dataframeKeys } from '../queryKeys';
import type { Instructions } from '../types';
import { isPreviewError } from '../types';

/**
 * Returns column names of the dataframe AT `upTo` step (i.e. after first `upTo` transforms).
 * For step index i, pass upTo=i to get the columns BEFORE this step is applied.
 * Reuses TanStack Query cache. Returns [] if preview failed or not yet loaded.
 */
export function usePreviewColumns({
  instructions,
  sessionId,
  upTo,
  enabled = true,
}: {
  instructions: Instructions;
  sessionId: string | null;
  upTo: number;
  enabled?: boolean;
}): { columns: string[]; isLoading: boolean } {
  // Trim instructions to the relevant prefix so re-edits of later steps
  // don't invalidate the cache for an earlier step's columns.
  const trimmed: Instructions = {
    ...instructions,
    transforms: instructions.transforms.slice(0, upTo),
  };

  const query = useQuery({
    queryKey: dataframeKeys.preview(sessionId ?? '', upTo, {
      instructions: trimmed,
      rowLimit: 1,
    }),
    queryFn: () =>
      previewPipeline({
        instructions: trimmed,
        sessionId: sessionId as string,
        upTo,
        rowLimit: 1,
      }),
    enabled: enabled && !!sessionId && !!instructions.reader.func,
    retry: false,
    staleTime: 30_000,
  });

  const columns =
    query.data && !isPreviewError(query.data) ? query.data.columns : [];
  return { columns, isLoading: query.isLoading };
}
