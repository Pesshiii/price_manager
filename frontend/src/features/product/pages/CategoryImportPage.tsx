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
import { useCallback, useEffect, useRef, useState } from 'react';
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
import { CategoryMappingStep } from '../components/import/CategoryMappingStep';
import { CategoryPreviewResults } from '../components/import/CategoryPreviewResults';
import {
  useCategoryImportCommit,
  useCategoryImportJob,
  useCategoryImportJobInvalidation,
  useCategoryImportPreview,
} from '../hooks/useCategoryImportMutations';
import type {
  CategoryImportCommitResult,
  CategoryImportMapping,
  CategoryImportPreviewResult,
  ImportJob,
} from '../types';

type SourceMode = 'saved' | 'adhoc';

const EMPTY_MAPPING: CategoryImportMapping = { path_column: '' };

export function CategoryImportPage() {
  const qc = useQueryClient();

  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<SourceMode>('saved');

  // Saved-mode state
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [pipelineId, setPipelineId] = useState<number | null>(null);
  const [savedInstructions, setSavedInstructions] = useState<Instructions | null>(null);

  // Ad-hoc-mode state
  const [adhocInstructions, setAdhocInstructions] = useState<Instructions>(emptyInstructions());
  const [adhocSessionId, setAdhocSessionId] = useState<string | null>(null);
  const [adhocUploadedFile, setAdhocUploadedFile] = useState<{ name: string; size: number } | null>(null);
  const [adhocSelectedStep, setAdhocSelectedStep] = useState<number | null>(null);

  // Shared state
  const [columns, setColumns] = useState<string[]>([]);
  const [mapping, setMapping] = useState<CategoryImportMapping>(EMPTY_MAPPING);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [commitJobId, setCommitJobId] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<CategoryImportPreviewResult | null>(null);
  const [commitResult, setCommitResult] = useState<CategoryImportCommitResult | null>(null);

  const [saveModalOpened, { open: openSave, close: closeSave }] = useDisclosure(false);
  const [saveName, setSaveName] = useState('');

  const handledPreviewRef = useRef<string | null>(null);
  const handledCommitRef = useRef<string | null>(null);

  const registry = useDataframeRegistry();
  const { data: pipelines } = useQuery({
    queryKey: dataframeKeys.pipelines(),
    queryFn: listPipelines,
  });

  const currentSessionId = mode === 'saved' ? sessionId : adhocSessionId;
  const currentInstructions = mode === 'saved' ? savedInstructions : adhocInstructions;

  useEffect(() => {
    if (mode !== 'saved' || pipelineId == null || savedInstructions || !pipelines) return;
    const found = pipelines.find((p: DataframePayload) => p.id === pipelineId);
    if (found) setSavedInstructions(found.instructions);
  }, [pipelines, pipelineId, mode, savedInstructions]);

  const resetDownstream = useCallback(() => {
    setStep(0);
    setMapping(EMPTY_MAPPING);
    setColumns([]);
    setPreviewJobId(null);
    setCommitJobId(null);
    setPreviewResult(null);
    setCommitResult(null);
    handledPreviewRef.current = null;
    handledCommitRef.current = null;
  }, []);

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadSession(file),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setFilename(data.filename);
    },
  });

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

  const previewMutation = useCategoryImportPreview();
  const commitMutation = useCategoryImportCommit();
  const invalidateAfterCommit = useCategoryImportJobInvalidation();

  const previewJobQuery = useCategoryImportJob(previewJobId);
  const commitJobQuery = useCategoryImportJob(commitJobId);

  useEffect(() => {
    const job = previewJobQuery.data;
    if (!job) return;
    if (job.status !== 'success' && job.status !== 'error') return;
    const key = `${job.id}:${job.status}`;
    if (handledPreviewRef.current === key) return;
    handledPreviewRef.current = key;
    if (job.status === 'success' && job.result) {
      setPreviewResult(job.result as unknown as CategoryImportPreviewResult);
    } else if (job.status === 'error') {
      notifications.show({
        message: job.error || 'Ошибка при подготовке превью',
        color: 'red',
      });
    }
  }, [previewJobQuery.data]);

  useEffect(() => {
    const job = commitJobQuery.data;
    if (!job) return;
    if (job.status !== 'success' && job.status !== 'error') return;
    const key = `${job.id}:${job.status}`;
    if (handledCommitRef.current === key) return;
    handledCommitRef.current = key;
    if (job.status === 'success' && job.result) {
      const result = job.result as unknown as CategoryImportCommitResult;
      setCommitResult(result);
      invalidateAfterCommit(job as ImportJob);
      notifications.show({
        message: `Создано узлов: ${result.created}, пропущено: ${result.skipped}`,
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

  const runPreview = () => {
    if (!currentSessionId || !currentInstructions) return;
    setPreviewResult(null);
    handledPreviewRef.current = null;
    previewMutation.mutate(
      {
        session_id: currentSessionId,
        instructions: currentInstructions,
        mapping,
        row_limit: 200,
      },
      {
        onSuccess: (job) => {
          setPreviewJobId(job.id);
          setStep(2);
        },
      },
    );
  };

  const runCommit = () => {
    if (!currentSessionId || !currentInstructions) return;
    setCommitResult(null);
    handledCommitRef.current = null;
    commitMutation.mutate(
      { session_id: currentSessionId, instructions: currentInstructions, mapping },
      {
        onSuccess: (job) => setCommitJobId(job.id),
      },
    );
  };

  const cleanupSession = async () => {
    const toDelete = new Set<string>();
    if (sessionId) toDelete.add(sessionId);
    if (adhocSessionId) toDelete.add(adhocSessionId);
    await Promise.all([...toDelete].map((sid) => deleteSession(sid).catch(() => undefined)));
    setSessionId(null);
    setFilename(null);
    setAdhocSessionId(null);
    setAdhocUploadedFile(null);
    setAdhocInstructions(emptyInstructions());
    setPipelineId(null);
    setSavedInstructions(null);
    resetDownstream();
  };

  const canProceedToMapping =
    mode === 'saved'
      ? !!sessionId && !!savedInstructions
      : !!adhocSessionId && columns.length > 0;

  const mappingValid = !!mapping.path_column;

  const previewJobStatus = previewJobQuery.data?.status;
  const commitJobStatus = commitJobQuery.data?.status;
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
      <Title order={2}>Импорт категорий</Title>

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

        <Stepper.Step label="Маппинг" description="Колонка с путём">
          <Stack mt="md">
            <CategoryMappingStep
              columns={columns}
              mapping={mapping}
              onChange={setMapping}
            />
            <Group justify="space-between">
              <Button variant="default" onClick={() => setStep(0)}>
                Назад
              </Button>
              <Button
                onClick={runPreview}
                loading={previewInFlight}
                disabled={!mappingValid}
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
            {previewResult && <CategoryPreviewResults result={previewResult} />}
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
                Создано узлов: {commitResult.created}, пропущено: {commitResult.skipped}
                {commitResult.invalid > 0 && `, с ошибками: ${commitResult.invalid}`}
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
                  onClick={runCommit}
                  loading={commitInFlight}
                  disabled={!previewResult || previewResult.new === 0}
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
