import { useEffect, useState } from 'react';
import { Alert, Loader, Stack } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { createPipeline, getPipeline, updatePipeline } from '../api';
import {
  DataframeBuilder,
  type UploadedFileInfo,
} from '../components/DataframeBuilder';
import { UndoRedoToolbar } from '../components/UndoRedoToolbar';
import { useDataframeRegistry } from '../hooks/useDataframeRegistry';
import { useSessionRestore } from '../hooks/useSessionRestore';
import { useUndoableState } from '../hooks/useUndoableState';
import { dataframeKeys } from '../queryKeys';
import type { DataframePayload, Instructions } from '../types';
import { emptyInstructions } from '../types';

export function DataframeEditorPage() {
  const params = useParams();
  const id = params.id ? Number(params.id) : null;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const registry = useDataframeRegistry();
  const pipelineQuery = useQuery<DataframePayload>({
    queryKey: id != null ? dataframeKeys.pipeline(id) : ['noop'],
    queryFn: () => getPipeline(id as number),
    enabled: id != null,
  });

  const [name, setName] = useState('');
  const [savedName, setSavedName] = useState('');
  const undoable = useUndoableState<Instructions>(emptyInstructions());
  const [savedSnapshot, setSavedSnapshot] = useState<Instructions>(emptyInstructions());
  const [sessionId, setSessionId] = useState<string | null>(searchParams.get('session'));
  const [uploadedFile, setUploadedFile] = useState<UploadedFileInfo | null>(null);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);

  useEffect(() => {
    if (pipelineQuery.data) {
      const data = pipelineQuery.data;
      setName(data.name);
      setSavedName(data.name);
      undoable.reset(data.instructions);
      setSavedSnapshot(data.instructions);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineQuery.data]);

  const instructions = undoable.value;

  // sync sessionId -> URL
  useEffect(() => {
    if (sessionId && searchParams.get('session') !== sessionId) {
      const next = new URLSearchParams(searchParams);
      next.set('session', sessionId);
      setSearchParams(next, { replace: true });
    }
    if (!sessionId && searchParams.has('session')) {
      const next = new URLSearchParams(searchParams);
      next.delete('session');
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useSessionRestore(sessionId, uploadedFile, setUploadedFile, setSessionId);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (id == null) return createPipeline({ name, description: '', instructions });
      return updatePipeline(id, { name, description: '', instructions });
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: dataframeKeys.pipelines() });
      qc.setQueryData(dataframeKeys.pipeline(data.id), data);
      setSavedSnapshot(data.instructions);
      setSavedName(data.name);
      notifications.show({
        message: id == null ? 'Пайплайн создан' : 'Пайплайн сохранён',
        color: 'green',
      });
      if (id == null) {
        const search = sessionId ? `?session=${sessionId}` : '';
        navigate(`/dataframe/${data.id}${search}`, { replace: true });
      }
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: unknown } })?.response?.data ?? e;
      notifications.show({
        message: typeof msg === 'string' ? msg : JSON.stringify(msg),
        color: 'red',
      });
    },
  });

  const dirty =
    JSON.stringify(instructions) !== JSON.stringify(savedSnapshot) || name !== savedName;
  const canSave = name.trim().length > 0 && !!instructions.reader.func;

  if (registry.isLoading || (id != null && pipelineQuery.isLoading)) {
    return <Loader />;
  }

  if (registry.isError || !registry.data) {
    return <Alert color="red">Не удалось загрузить registry</Alert>;
  }

  return (
    <Stack gap="md">
      <UndoRedoToolbar
        name={name}
        onChangeName={setName}
        onCommitName={() => undoable.set(instructions)}
        onUndo={undoable.undo}
        onRedo={undoable.redo}
        canUndo={undoable.canUndo}
        canRedo={undoable.canRedo}
        onSave={() => saveMutation.mutate()}
        saving={saveMutation.isPending}
        dirty={dirty}
        canSave={canSave}
      />

      <DataframeBuilder
        registry={registry.data}
        instructions={instructions}
        setInstructions={(next) => undoable.set(next)}
        replaceInstructions={(next) => undoable.replace(next)}
        commitInstructions={() => undoable.set(instructions)}
        sessionId={sessionId}
        setSessionId={setSessionId}
        uploadedFile={uploadedFile}
        setUploadedFile={setUploadedFile}
        selectedStep={selectedStep}
        setSelectedStep={setSelectedStep}
      />
    </Stack>
  );
}
