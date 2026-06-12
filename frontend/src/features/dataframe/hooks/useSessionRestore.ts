import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSession } from '../api';
import { dataframeKeys } from '../queryKeys';
import type { UploadedFileInfo } from '../components/DataframeBuilder';

export function useSessionRestore(
  sessionId: string | null,
  uploadedFile: UploadedFileInfo | null,
  setUploadedFile: (f: UploadedFileInfo | null) => void,
  setSessionId: (s: string | null) => void,
) {
  const query = useQuery({
    queryKey: dataframeKeys.session(sessionId ?? ''),
    queryFn: () => getSession(sessionId as string),
    enabled: !!sessionId && !uploadedFile,
    retry: false,
  });

  useEffect(() => {
    if (query.data) {
      setUploadedFile({ name: query.data.filename, size: query.data.size });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.data]);

  useEffect(() => {
    const status = (query.error as { response?: { status?: number } } | null)?.response
      ?.status;
    if (status === 404) {
      setSessionId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.error]);

  return query;
}
