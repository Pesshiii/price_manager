import { useInfiniteQuery } from '@tanstack/react-query';
import { previewPipeline } from '../api';
import { dataframeKeys } from '../queryKeys';
import type { Instructions, PreviewResult } from '../types';
import { isPreviewError } from '../types';
import { useDebouncedValue } from './useDebouncedValue';

export interface UsePreviewArgs {
  instructions: Instructions;
  sessionId: string | null;
  upTo?: number;
  rowLimit?: number;
  debounceMs?: number;
}

export function usePipelinePreview({
  instructions,
  sessionId,
  upTo,
  rowLimit = 100,
  debounceMs = 300,
}: UsePreviewArgs) {
  const debounced = useDebouncedValue(instructions, debounceMs);
  const debouncedUpTo = useDebouncedValue(upTo, debounceMs);

  return useInfiniteQuery<PreviewResult, Error, { pages: PreviewResult[]; pageParams: number[] }, ReturnType<typeof dataframeKeys.preview>, number>({
    queryKey: dataframeKeys.preview(sessionId ?? '', debouncedUpTo, {
      instructions: debounced,
      rowLimit,
    }),
    queryFn: ({ pageParam }) =>
      previewPipeline({
        instructions: debounced,
        sessionId: sessionId as string,
        upTo: debouncedUpTo,
        rowLimit,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      if (isPreviewError(last)) return undefined;
      return last.has_more ? last.offset + last.returned_rows : undefined;
    },
    enabled: !!sessionId && !!debounced.reader.func,
    retry: false,
  });
}
