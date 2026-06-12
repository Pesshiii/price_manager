import {
  Alert,
  Button,
  Card,
  FileButton,
  Group,
  Loader,
  Modal,
  Radio,
  Select,
  Stack,
  Stepper,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconUpload } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createPipeline,
  deleteSession,
  listPipelines,
  previewPipeline,
  uploadSession,
} from '@/features/dataframe/api';
import { DataframeBuilder } from '@/features/dataframe/components/DataframeBuilder';
import { useDataframeRegistry } from '@/features/dataframe/hooks/useDataframeRegistry';
import { dataframeKeys } from '@/features/dataframe/queryKeys';
import {
  emptyInstructions,
  isPreviewError,
  type DataframePayload,
  type Instructions,
  type PreviewSuccess,
} from '@/features/dataframe/types';
import { ImportMappingStep } from '../components/import/ImportMappingStep';
import { ImportPreviewResults } from '../components/import/ImportPreviewResults';
import { useCharacteristicTypes } from '../hooks/useCharacteristicTypes';
import {
  useImportCommit,
  useImportJob,
  useImportJobInvalidation,
  useImportPreview,
} from '../hooks/useImportMutations';
import { useImportPersistence } from '../hooks/useImportPersistence';
import { useImportSessionRestore } from '../hooks/useImportSessionRestore';
import {
  clearPersistedState,
  defaultPersistedState,
  loadPersistedState,
  type SourceMode,
} from '../persistence';
import type {
  ImportCommitResult,
  ImportJob,
  ImportMapping,
  ImportPreviewResult,
} from '../types';

export function ImportPage() {
  const qc = useQueryClient();
  const initial = useMemo(() => loadPersistedState() ?? defaultPersistedState(), []);

  const [step, setStep] = useState<number>(initial.step);
  const [mode, setMode] = useState<SourceMode>(initial.mode);

  // Saved-mode state
  const [sessionId, setSessionId] = useState<string | null>(initial.sessionId);
  const [filename, setFilename] = useState<string | null>(initial.filename);
  const [pipelineId, setPipelineId] = useState<number | null>(initial.pipelineId);
  const [savedInstructions, setSavedInstructions] = useState<Instructions | null>(null);

  // Ad-hoc-mode state
  const [adhocInstructions, setAdhocInstructions] = useState<Instructions>(initial.adhocInstructions);
  const [adhocSessionId, setAdhocSessionId] = useState<string | null>(initial.adhocSessionId);
  const [adhocUploadedFile, setAdhocUploadedFile] = useState(initial.adhocUploadedFile);
  const [adhocSelectedStep, setAdhocSelectedStep] = useState<number | null>(null);

  // Shared step-2/3 state
  const [columns, setColumns] = useState<string[]>(initial.columns);
  const [mapping, setMapping] = useState<ImportMapping>(initial.mapping);
  const [previewJobId, setPreviewJobId] = useState<string | null>(initial.previewJobId);
  const [commitJobId, setCommitJobId] = useState<string | null>(initial.commitJobId);
  const [previewResult, setPreviewResult] = useState<ImportPreviewResult | null>(
    initial.previewResult,
  );
  const [commitResult, setCommitResult] = useState<ImportCommitResult | null>(
    initial.commitResult,
  );

  const [saveModalOpened, { open: openSave, close: closeSave }] = useDisclosure(false);
  const [saveName, setSaveName] = useState('');

  // Each ref stores `${jobId}:${terminalStatus}` once we've handled it, so
  // re-renders / re-fetches with identical data don't re-fire the toast.
  const handledPreviewRef = useRef<string | null>(null);
  const handledCommitRef = useRef<string | null>(null);

  const registry = useDataframeRegistry();
  const { data: pipelines } = useQuery({
    queryKey: dataframeKeys.pipelines(),
    queryFn: listPipelines,
  });
  // Bound-chars metadata only. After EAV-import the catalog can hold thousands
  // of types — never load the whole list here, that froze the browser. The
  // ImportMappingStep ships its own ?search=-driven autocomplete picker for
  // discovering new types; here we just pre-fetch labels/units for the chars
  // already bound in the current mapping (typically a handful).
  const boundCharNames = useMemo(
    () => Object.keys(mapping.characteristics ?? {}),
    [mapping],
  );
  const { data: boundCharTypesPage } = useCharacteristicTypes(
    boundCharNames.length > 0
      ? { name__in: boundCharNames, page_size: 500 }
      : {},
  );
  const charTypes = boundCharNames.length > 0
    ? boundCharTypesPage?.results ?? []
    : [];

  // Resolve current session+instructions depending on mode
  const currentSessionId = mode === 'saved' ? sessionId : adhocSessionId;
  const currentInstructions = mode === 'saved' ? savedInstructions : adhocInstructions;

  // Re-resolve savedInstructions when pipelines load after hydration.
  useEffect(() => {
    if (mode !== 'saved' || pipelineId == null || savedInstructions || !pipelines) return;
    const found = pipelines.find((p: DataframePayload) => p.id === pipelineId);
    if (found) setSavedInstructions(found.instructions);
  }, [pipelines, pipelineId, mode, savedInstructions]);

  const resetDownstream = useCallback(() => {
    setStep(0);
    setMapping({});
    setColumns([]);
    setPreviewJobId(null);
    setCommitJobId(null);
    setPreviewResult(null);
    setCommitResult(null);
    handledPreviewRef.current = null;
    handledCommitRef.current = null;
  }, []);

  useImportSessionRestore({
    sessionId,
    adhocSessionId,
    setSessionId,
    setFilename,
    setAdhocSessionId,
    setAdhocUploadedFile,
    onAnyInvalidated: resetDownstream,
  });

  useImportPersistence({
    version: 3,
    mode,
    step: (step === 1 || step === 2 ? step : 0) as 0 | 1 | 2,
    sessionId,
    filename,
    pipelineId,
    adhocSessionId,
    adhocUploadedFile,
    adhocInstructions,
    columns,
    mapping,
    previewJobId,
    commitJobId,
    previewResult,
    commitResult,
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadSession(file),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setFilename(data.filename);
    },
  });

  // For saved mode — explicitly run pipeline preview to fetch column list
  const savedPreviewMutation = useMutation({
    mutationFn: (args: { sessionId: string; instructions: Instructions }) =>
      previewPipeline({
        instructions: args.instructions,
        sessionId: args.sessionId,
        rowLimit: 50,
      }),
    onSuccess: (result) => {
      if (isPreviewError(result)) {
        notifications.show({ message: result.error.message, color: 'red' });
        return;
      }
      const success = result as PreviewSuccess;
      setColumns(success.columns);
      setStep(1);
    },
  });

  const previewMutation = useImportPreview();
  const commitMutation = useImportCommit();
  const invalidateAfterCommit = useImportJobInvalidation();

  const previewJobQuery = useImportJob(previewJobId);
  const commitJobQuery = useImportJob(commitJobId);

  // Persist preview job result once it lands — exactly once per (jobId, status).
  useEffect(() => {
    const job = previewJobQuery.data;
    if (!job) return;
    if (job.status !== 'success' && job.status !== 'error') return;
    const key = `${job.id}:${job.status}`;
    if (handledPreviewRef.current === key) return;
    handledPreviewRef.current = key;
    if (job.status === 'success' && job.result) {
      setPreviewResult(job.result as ImportPreviewResult);
    } else if (job.status === 'error') {
      notifications.show({
        message: job.error || 'Ошибка при подготовке превью',
        color: 'red',
      });
    }
  }, [previewJobQuery.data]);

  // Persist commit job result once it lands — exactly once per (jobId, status).
  useEffect(() => {
    const job = commitJobQuery.data;
    if (!job) return;
    if (job.status !== 'success' && job.status !== 'error') return;
    const key = `${job.id}:${job.status}`;
    if (handledCommitRef.current === key) return;
    handledCommitRef.current = key;
    if (job.status === 'success' && job.result) {
      const result = job.result as ImportCommitResult;
      setCommitResult(result);
      invalidateAfterCommit(job as ImportJob);
      notifications.show({
        message: `Создано: ${result.created}, обновлено: ${result.updated}`,
        color: 'green',
      });
    } else if (job.status === 'error') {
      notifications.show({
        message: job.error || 'Ошибка при импорте',
        color: 'red',
      });
    }
  }, [commitJobQuery.data, invalidateAfterCommit]);

  const savePipelineMutation = useMutation({
    mutationFn: () =>
      createPipeline({
        name: saveName.trim(),
        description: '',
        instructions: adhocInstructions,
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: dataframeKeys.pipelines() });
      qc.setQueryData(dataframeKeys.pipeline(data.id), data);
      notifications.show({ message: `Пайплайн «${data.name}» создан`, color: 'green' });
      closeSave();
      setSaveName('');
      // Switch to saved-mode binding the freshly created pipeline + current session
      setMode('saved');
      setPipelineId(data.id);
      setSavedInstructions(data.instructions);
      setSessionId(adhocSessionId);
      setFilename(adhocUploadedFile?.name ?? null);
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: unknown } })?.response?.data ?? e;
      notifications.show({
        message: typeof msg === 'string' ? msg : JSON.stringify(msg),
        color: 'red',
      });
    },
  });

  const handlePipelineSelect = (id: string | null) => {
    if (!id || !pipelines) {
      setPipelineId(null);
      setSavedInstructions(null);
      return;
    }
    const num = Number(id);
    const found = pipelines.find((p: DataframePayload) => p.id === num);
    setPipelineId(num);
    setSavedInstructions(found?.instructions ?? null);
  };

  const forkToAdhoc = () => {
    if (!savedInstructions) return;
    setAdhocInstructions(savedInstructions);
    setAdhocSessionId(sessionId);
    setAdhocUploadedFile(filename ? { name: filename, size: 0 } : null);
    setMode('adhoc');
  };

  const goToMapping = () => {
    if (mode === 'saved') {
      if (!sessionId || !savedInstructions) return;
      savedPreviewMutation.mutate({ sessionId, instructions: savedInstructions });
    } else {
      // In ad-hoc mode we rely on the builder's live preview to have populated `columns`
      if (columns.length === 0) {
        notifications.show({
          message: 'Дождитесь успешного превью с колонками',
          color: 'orange',
        });
        return;
      }
      setStep(1);
    }
  };

  const runImportPreview = () => {
    if (!currentSessionId || !currentInstructions) return;
    setPreviewResult(null);
    previewMutation.mutate(
      {
        session_id: currentSessionId,
        instructions: currentInstructions,
        mapping,
        row_limit: 100,
      },
      {
        onSuccess: (job) => {
          setPreviewJobId(job.id);
          setStep(2);
        },
      },
    );
  };

  const runImportCommit = () => {
    if (!currentSessionId || !currentInstructions) return;
    setCommitResult(null);
    commitMutation.mutate(
      { session_id: currentSessionId, instructions: currentInstructions, mapping },
      {
        onSuccess: (job) => setCommitJobId(job.id),
      },
    );
  };

  const cleanupSession = async () => {
    const sessionsToDelete = new Set<string>();
    if (sessionId) sessionsToDelete.add(sessionId);
    if (adhocSessionId) sessionsToDelete.add(adhocSessionId);
    await Promise.all(
      [...sessionsToDelete].map((sid) => deleteSession(sid).catch(() => undefined)),
    );
    setSessionId(null);
    setFilename(null);
    setAdhocSessionId(null);
    setAdhocUploadedFile(null);
    setAdhocInstructions(emptyInstructions());
    setColumns([]);
    setMapping({});
    setPreviewJobId(null);
    setCommitJobId(null);
    setPreviewResult(null);
    setCommitResult(null);
    handledPreviewRef.current = null;
    handledCommitRef.current = null;
    setStep(0);
    setPipelineId(null);
    setSavedInstructions(null);
    clearPersistedState();
  };

  const canProceedToMapping =
    mode === 'saved'
      ? !!sessionId && !!savedInstructions
      : !!adhocSessionId && columns.length > 0;

  const previewJobStatus = previewJobQuery.data?.status;
  const commitJobStatus = commitJobQuery.data?.status;
  // Dynamic groups must have both name_column and value_column or be empty —
  // a half-filled group means the user forgot to pick a column.
  const dynamicGroupsValid = (mapping.dynamic_characteristics ?? []).every(
    (spec) => Boolean(spec.name_column) === Boolean(spec.value_column),
  );
  const previewInFlight =
    previewMutation.isPending ||
    previewJobStatus === 'pending' ||
    previewJobStatus === 'running';
  const commitInFlight =
    commitMutation.isPending ||
    commitJobStatus === 'pending' ||
    commitJobStatus === 'running';

  return (
    <Stack>
      <Title order={2}>Импорт товаров</Title>

      <Stepper active={step} onStepClick={setStep}>
        <Stepper.Step label="Источник" description="Файл и пайплайн">
          <Stack mt="md">
            <Radio.Group
              value={mode}
              onChange={(v) => setMode(v as SourceMode)}
              label="Режим"
            >
              <Group mt="xs">
                <Radio value="saved" label="Сохранённый пайплайн" />
                <Radio value="adhoc" label="Ad-hoc" />
              </Group>
            </Radio.Group>

            {mode === 'saved' && (
              <Card withBorder padding="md">
                <Stack>
                  <Group>
                    <FileButton
                      onChange={(f) => f && uploadMutation.mutate(f)}
                      accept="*"
                    >
                      {(props) => (
                        <Button
                          {...props}
                          leftSection={<IconUpload size={16} />}
                          loading={uploadMutation.isPending}
                        >
                          Загрузить файл
                        </Button>
                      )}
                    </FileButton>
                    {filename && <Text c="dimmed">{filename}</Text>}
                  </Group>
                  <Select
                    label="Пайплайн"
                    placeholder="Выберите сохранённый пайплайн"
                    data={(pipelines ?? []).map((p) => ({
                      value: String(p.id),
                      label: p.name,
                    }))}
                    value={pipelineId !== null ? String(pipelineId) : null}
                    onChange={handlePipelineSelect}
                    searchable
                  />
                  <Group>
                    <Button
                      variant="default"
                      onClick={forkToAdhoc}
                      disabled={!savedInstructions}
                    >
                      Форкнуть в ad-hoc
                    </Button>
                  </Group>
                </Stack>
              </Card>
            )}

            {mode === 'adhoc' && (
              <Card withBorder padding="md">
                <Stack>
                  {registry.isLoading && <Loader />}
                  {registry.data && (
                    <DataframeBuilder
                      registry={registry.data}
                      instructions={adhocInstructions}
                      setInstructions={setAdhocInstructions}
                      sessionId={adhocSessionId}
                      setSessionId={setAdhocSessionId}
                      uploadedFile={adhocUploadedFile}
                      setUploadedFile={setAdhocUploadedFile}
                      selectedStep={adhocSelectedStep}
                      setSelectedStep={setAdhocSelectedStep}
                      onPreviewSuccess={(p) => setColumns(p.columns)}
                    />
                  )}
                  <Group justify="flex-end">
                    <Button
                      variant="default"
                      onClick={openSave}
                      disabled={!adhocInstructions.reader.func}
                    >
                      Сохранить как pipeline…
                    </Button>
                  </Group>
                </Stack>
              </Card>
            )}

            <Group justify="flex-end">
              <Button
                onClick={goToMapping}
                disabled={!canProceedToMapping}
                loading={savedPreviewMutation.isPending}
              >
                Далее
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Маппинг" description="Поля → колонки">
          <Stack mt="md">
            <ImportMappingStep
              columns={columns}
              characteristicTypes={charTypes ?? []}
              mapping={mapping}
              onChange={setMapping}
            />
            <Group justify="space-between">
              <Button variant="default" onClick={() => setStep(0)}>
                Назад
              </Button>
              <Button
                onClick={runImportPreview}
                loading={previewInFlight}
                disabled={!dynamicGroupsValid}
              >
                Проверить
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Импорт" description="Проверка и сохранение">
          <Stack mt="md">
            {previewInFlight && !previewResult && (
              <Group>
                <Loader size="sm" />
                <Text c="dimmed">{previewJobQuery.data?.stage || 'Готовится превью…'}</Text>
              </Group>
            )}
            {previewResult && <ImportPreviewResults result={previewResult} />}
            {commitInFlight && (
              <Group>
                <Loader size="sm" />
                <Text c="dimmed">
                  {commitJobQuery.data?.stage || 'Импортируем — можно подождать или вернуться позже'}
                </Text>
              </Group>
            )}
            {commitResult && (
              <Alert color="green" title="Импорт выполнен">
                Создано: {commitResult.created}, обновлено: {commitResult.updated},
                пропущено: {commitResult.skipped}
              </Alert>
            )}
            <Group justify="space-between">
              <Button variant="default" onClick={() => setStep(1)}>
                Назад
              </Button>
              <Group>
                <Button variant="subtle" onClick={cleanupSession}>
                  Сбросить
                </Button>
                <Button
                  onClick={runImportCommit}
                  loading={commitInFlight}
                  disabled={!previewResult || previewResult.valid === 0}
                >
                  Импортировать
                </Button>
              </Group>
            </Group>
          </Stack>
        </Stepper.Step>
      </Stepper>

      <Modal
        opened={saveModalOpened}
        onClose={closeSave}
        title="Сохранить ad-hoc как pipeline"
      >
        <Stack>
          <TextInput
            label="Имя пайплайна"
            value={saveName}
            onChange={(e) => setSaveName(e.currentTarget.value)}
            required
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={closeSave}>
              Отмена
            </Button>
            <Button
              loading={savePipelineMutation.isPending}
              disabled={!saveName.trim() || !adhocInstructions.reader.func}
              onClick={() => savePipelineMutation.mutate()}
            >
              Сохранить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
