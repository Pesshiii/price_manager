import { Alert, Button, Drawer, Group, Loader, Stack, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { createPipeline, deleteSession } from '@/features/dataframe/api';
import { DataframeBuilder, type UploadedFileInfo } from '@/features/dataframe/components/DataframeBuilder';
import { useDataframeRegistry } from '@/features/dataframe/hooks/useDataframeRegistry';
import { useUndoableState } from '@/features/dataframe/hooks/useUndoableState';
import { dataframeKeys } from '@/features/dataframe/queryKeys';
import { emptyInstructions, type DataframePayload, type PreviewSuccess } from '@/features/dataframe/types';

interface NewPipelineDrawerProps {
  opened: boolean;
  onClose: () => void;
  onCreated: (pipeline: DataframePayload, previewColumns: string[]) => void;
}

export function NewPipelineDrawer({ opened, onClose, onCreated }: NewPipelineDrawerProps) {
  const qc = useQueryClient();
  const registry = useDataframeRegistry();

  const [name, setName] = useState('');
  const undoable = useUndoableState(emptyInstructions());
  const [sessionId, setSessionIdState] = useState<string | null>(null);
  const [uploadedFile, setUploadedFile] = useState<UploadedFileInfo | null>(null);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  const [previewColumns, setPreviewColumns] = useState<string[]>([]);

  // Ref for cleanup on unmount — state may be stale in effect cleanup
  const sessionIdRef = useRef<string | null>(null);
  const setSessionId = (sid: string | null) => {
    sessionIdRef.current = sid;
    setSessionIdState(sid);
  };

  useEffect(() => {
    if (opened) {
      setName('');
      undoable.reset(emptyInstructions());
      setSessionId(null);
      setUploadedFile(null);
      setSelectedStep(null);
      setPreviewColumns([]);
    }
  }, [opened]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      if (sessionIdRef.current) {
        deleteSession(sessionIdRef.current).catch(() => undefined);
      }
    };
  }, []);

  const handleClose = () => {
    if (sessionIdRef.current) {
      deleteSession(sessionIdRef.current).catch(() => undefined);
      setSessionId(null);
    }
    onClose();
  };

  const handlePreviewSuccess = (preview: PreviewSuccess) => {
    setPreviewColumns(preview.columns);
  };

  const saveMutation = useMutation({
    mutationFn: () =>
      createPipeline({ name: name.trim(), description: '', instructions: undoable.value }),
    onSuccess: (pipeline) => {
      qc.invalidateQueries({ queryKey: dataframeKeys.pipelines() });
      notifications.show({ message: `Пайплайн «${pipeline.name}» создан`, color: 'green' });
      onCreated(pipeline, previewColumns);
      onClose();
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: unknown } })?.response?.data ?? e;
      notifications.show({
        message: typeof msg === 'string' ? msg : JSON.stringify(msg),
        color: 'red',
      });
    },
  });

  const canSave = name.trim().length > 0 && !!undoable.value.reader.func;

  return (
    <Drawer
      opened={opened}
      onClose={handleClose}
      title="Новый пайплайн"
      size="90%"
      position="right"
      styles={{ body: { overflowY: 'auto' } }}
    >
      <Stack gap="md">
        <TextInput
          label="Название пайплайна"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
        />

        {registry.isLoading && <Loader />}
        {registry.isError && <Alert color="red">Не удалось загрузить registry</Alert>}

        {registry.data && (
          <DataframeBuilder
            registry={registry.data}
            instructions={undoable.value}
            setInstructions={undoable.set}
            replaceInstructions={undoable.replace}
            commitInstructions={() => undoable.set(undoable.value)}
            sessionId={sessionId}
            setSessionId={setSessionId}
            uploadedFile={uploadedFile}
            setUploadedFile={setUploadedFile}
            selectedStep={selectedStep}
            setSelectedStep={setSelectedStep}
            onPreviewSuccess={handlePreviewSuccess}
          />
        )}

        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={handleClose}>
            Отмена
          </Button>
          <Button
            loading={saveMutation.isPending}
            disabled={!canSave}
            onClick={() => saveMutation.mutate()}
          >
            Сохранить и выбрать
          </Button>
        </Group>
      </Stack>
    </Drawer>
  );
}
