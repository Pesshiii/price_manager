import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  commitRename,
  commitRetype,
  getCharMutationJob,
  previewRename,
  previewRetype,
} from '../api';
import { charMutationJobKeys, charTypeKeys, productKeys } from '../queryKeys';
import type { CharMutationJob } from '../types';

/**
 * Wrappers around the safe-mutation endpoints. Preview mutations are simple
 * (no cache touching). Commit mutations return a CharMutationJob that the
 * caller polls via `useCharMutationJob`.
 */

export function useRetypePreview() {
  return useMutation({
    mutationFn: ({ id, new_value_type }: { id: number; new_value_type: import('../types').ValueType }) =>
      previewRetype(id, { new_value_type }),
  });
}

export function useRetypeCommit() {
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: import('../types').RetypeCommitPayload }) =>
      commitRetype(id, body),
  });
}

export function useRenamePreview() {
  return useMutation({
    mutationFn: ({ id, new_name }: { id: number; new_name: string }) =>
      previewRename(id, { new_name }),
  });
}

export function useRenameCommit() {
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: import('../types').RenameCommitPayload }) =>
      commitRename(id, body),
  });
}

/**
 * Polls `/characteristic-types/jobs/<id>/` every 2s while the job is
 * pending/running. Pass `null` to suspend. Mirrors `useImportJob`.
 */
export function useCharMutationJob(jobId: string | null) {
  return useQuery({
    queryKey: charMutationJobKeys.detail(jobId),
    queryFn: () => getCharMutationJob(jobId as string),
    enabled: jobId != null,
    refetchInterval: (query) => {
      const data = query.state.data as CharMutationJob | undefined;
      if (!data) return 2000;
      return data.status === 'pending' || data.status === 'running' ? 2000 : false;
    },
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
}

/**
 * Invalidate downstream caches after a retype/rename success. Touches both
 * `charTypeKeys.all` (the type metadata changed) and `productKeys.all` (every
 * product's JSONB may have been rewritten, so list/facet/detail are stale).
 */
export function useCharMutationInvalidation() {
  const qc = useQueryClient();
  return (job: CharMutationJob) => {
    if (job.status !== 'success') return;
    qc.invalidateQueries({ queryKey: charTypeKeys.all });
    qc.invalidateQueries({ queryKey: productKeys.all });
  };
}
