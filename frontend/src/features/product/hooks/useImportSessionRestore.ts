import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSession, type SessionMetadata } from '@/features/dataframe/api';
import type { UploadedFileInfo } from '@/features/dataframe/components/DataframeBuilder';
import { dataframeKeys } from '@/features/dataframe/queryKeys';

interface Args {
  sessionId: string | null;
  adhocSessionId: string | null;
  setSessionId: (s: string | null) => void;
  setFilename: (s: string | null) => void;
  setAdhocSessionId: (s: string | null) => void;
  setAdhocUploadedFile: (f: UploadedFileInfo | null) => void;
  onAnyInvalidated: () => void;
}

function status(error: unknown): number | undefined {
  return (error as { response?: { status?: number } } | null)?.response?.status;
}

export function useImportSessionRestore({
  sessionId,
  adhocSessionId,
  setSessionId,
  setFilename,
  setAdhocSessionId,
  setAdhocUploadedFile,
  onAnyInvalidated,
}: Args) {
  const savedQuery = useQuery<SessionMetadata>({
    queryKey: dataframeKeys.session(sessionId ?? ''),
    queryFn: () => getSession(sessionId as string),
    enabled: !!sessionId,
    retry: false,
  });

  const adhocQuery = useQuery<SessionMetadata>({
    queryKey: dataframeKeys.session(adhocSessionId ?? ''),
    queryFn: () => getSession(adhocSessionId as string),
    enabled: !!adhocSessionId,
    retry: false,
  });

  useEffect(() => {
    if (savedQuery.data) setFilename(savedQuery.data.filename);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedQuery.data]);

  useEffect(() => {
    if (adhocQuery.data) {
      setAdhocUploadedFile({
        name: adhocQuery.data.filename,
        size: adhocQuery.data.size,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adhocQuery.data]);

  useEffect(() => {
    if (status(savedQuery.error) !== 404) return;
    setSessionId(null);
    setFilename(null);
    const adhocAlive = !!adhocSessionId && status(adhocQuery.error) !== 404;
    if (!adhocAlive) onAnyInvalidated();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedQuery.error]);

  useEffect(() => {
    if (status(adhocQuery.error) !== 404) return;
    setAdhocSessionId(null);
    setAdhocUploadedFile(null);
    const savedAlive = !!sessionId && status(savedQuery.error) !== 404;
    if (!savedAlive) onAnyInvalidated();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adhocQuery.error]);
}
