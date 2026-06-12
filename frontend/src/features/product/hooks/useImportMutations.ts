import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { commitImport, getImportJob, previewImport } from '../api';
import { brandKeys, categoryKeys, importJobKeys, productKeys } from '../queryKeys';
import type { ImportJob } from '../types';

export function useImportPreview() {
  return useMutation({ mutationFn: previewImport });
}

export function useImportCommit() {
  return useMutation({ mutationFn: commitImport });
}

/**
 * Polls /import/jobs/<id>/ every 2s while the job is pending/running.
 * Pass `null` to suspend polling. On `success` for a commit job, the caller
 * should invalidate product/category/brand caches (see `useImportJobInvalidation`).
 */
export function useImportJob(jobId: string | null) {
  return useQuery({
    queryKey: importJobKeys.detail(jobId),
    queryFn: () => getImportJob(jobId as string),
    enabled: jobId != null,
    refetchInterval: (query) => {
      const data = query.state.data as ImportJob | undefined;
      if (!data) return 2000;
      return data.status === 'pending' || data.status === 'running' ? 2000 : false;
    },
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
}

/** Invalidate downstream caches once a commit job succeeds. */
export function useImportJobInvalidation() {
  const qc = useQueryClient();
  return (job: ImportJob) => {
    if (job.kind !== 'commit' || job.status !== 'success') return;
    qc.invalidateQueries({ queryKey: productKeys.all });
    qc.invalidateQueries({ queryKey: categoryKeys.all });
    qc.invalidateQueries({ queryKey: brandKeys.all });
  };
}
