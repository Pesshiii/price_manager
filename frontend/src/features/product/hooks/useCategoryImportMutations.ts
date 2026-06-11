import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { commitCategoryImport, getCategoryImportJob, previewCategoryImport } from '../api';
import { categoryImportJobKeys, categoryKeys } from '../queryKeys';
import type { ImportJob } from '../types';

export function useCategoryImportPreview() {
  return useMutation({ mutationFn: previewCategoryImport });
}

export function useCategoryImportCommit() {
  return useMutation({ mutationFn: commitCategoryImport });
}

export function useCategoryImportJob(jobId: string | null) {
  return useQuery({
    queryKey: categoryImportJobKeys.detail(jobId),
    queryFn: () => getCategoryImportJob(jobId as string),
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

export function useCategoryImportJobInvalidation() {
  const qc = useQueryClient();
  return (job: ImportJob) => {
    if (job.kind !== 'commit' || job.status !== 'success') return;
    qc.invalidateQueries({ queryKey: categoryKeys.all });
  };
}
