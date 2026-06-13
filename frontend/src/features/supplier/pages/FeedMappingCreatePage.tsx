import {
  Anchor,
  Autocomplete,
  Button,
  Card,
  Group,
  Loader,
  NumberInput,
  Select,
  Stack,
  Stepper,
  TagsInput,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconPlus } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { listPipelines } from '@/features/dataframe/api';
import { dataframeKeys } from '@/features/dataframe/queryKeys';
import type { DataframePayload } from '@/features/dataframe/types';
import { NewPipelineDrawer } from '../components/NewPipelineDrawer';
import { createFeedMapping } from '../api';
import { supplierKeys } from '../queryKeys';

export function FeedMappingCreatePage() {
  const { id } = useParams<{ id: string }>();
  const supplierId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [step, setStep] = useState(0);

  // Step 0: pipeline selection
  const [selectedPipelineId, setSelectedPipelineId] = useState<number | null>(null);
  const [selectedPipelineName, setSelectedPipelineName] = useState('');
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);
  const [drawerKey, setDrawerKey] = useState(0);
  const [drawerOpened, { open: openDrawer, close: closeDrawer }] = useDisclosure(false);

  // Step 1: mapping fields
  const [name, setName] = useState('');
  const [skuColumn, setSkuColumn] = useState('');
  const [nameColumn, setNameColumn] = useState('');
  const [variableColumns, setVariableColumns] = useState<string[]>([]);
  const [threshold, setThreshold] = useState<number>(0.92);
  const [lowMatchThreshold, setLowMatchThreshold] = useState<number>(0.5);

  const pipelinesQuery = useQuery({
    queryKey: dataframeKeys.pipelines(),
    queryFn: listPipelines,
  });

  const pipelineData = (pipelinesQuery.data ?? []).map((p) => ({
    value: String(p.id),
    label: p.name,
  }));

  const handlePipelineSelect = (value: string | null) => {
    if (value) {
      const pipeline = pipelinesQuery.data?.find((p) => p.id === Number(value));
      setSelectedPipelineId(Number(value));
      setSelectedPipelineName(pipeline?.name ?? '');
      setAvailableColumns([]);
    } else {
      setSelectedPipelineId(null);
      setSelectedPipelineName('');
      setAvailableColumns([]);
    }
  };

  const handlePipelineCreated = (pipeline: DataframePayload, previewColumns: string[]) => {
    setSelectedPipelineId(pipeline.id);
    setSelectedPipelineName(pipeline.name);
    setAvailableColumns(previewColumns);
  };

  const handleOpenDrawer = () => {
    setDrawerKey((k) => k + 1);
    openDrawer();
  };

  const createMutation = useMutation({
    mutationFn: () =>
      createFeedMapping({
        supplier: supplierId,
        name: name.trim(),
        dataframe: selectedPipelineId!,
        supplier_sku_column: skuColumn.trim(),
        name_column: nameColumn.trim(),
        variable_columns: variableColumns,
        auto_match_threshold: threshold,
        low_match_threshold: lowMatchThreshold,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: supplierKeys.mappings(supplierId) });
      notifications.show({ message: 'Маппинг создан', color: 'green' });
      navigate(`/suppliers/${supplierId}`);
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: unknown } })?.response?.data ?? e;
      notifications.show({
        message: typeof msg === 'string' ? msg : JSON.stringify(msg),
        color: 'red',
      });
    },
  });

  const canSubmit =
    name.trim().length > 0 &&
    selectedPipelineId !== null &&
    skuColumn.trim().length > 0 &&
    nameColumn.trim().length > 0;

  return (
    <Stack>
      <Group>
        <Anchor component={Link} to={`/suppliers/${supplierId}`} size="sm" c="dimmed">
          ← {selectedPipelineName ? 'Поставщик' : 'Поставщик'}
        </Anchor>
      </Group>

      <Title order={2}>Новый маппинг фида</Title>

      <Stepper active={step} onStepClick={setStep}>
        <Stepper.Step label="Пайплайн" description="Выбор или создание">
          <Stack gap="md" mt="md">
            {pipelinesQuery.isLoading && <Loader />}

            {!pipelinesQuery.isLoading && (
              <>
                <Select
                  label="Существующий пайплайн"
                  placeholder="Выберите пайплайн..."
                  data={pipelineData}
                  searchable
                  clearable
                  value={selectedPipelineId !== null ? String(selectedPipelineId) : null}
                  onChange={handlePipelineSelect}
                />

                <Group gap="xs" align="center">
                  <Text size="sm" c="dimmed">
                    или
                  </Text>
                  <Button
                    variant="light"
                    size="sm"
                    leftSection={<IconPlus size={14} />}
                    onClick={handleOpenDrawer}
                  >
                    Создать новый пайплайн
                  </Button>
                </Group>

                {selectedPipelineId !== null && (
                  <Card withBorder padding="sm" bg="green.0">
                    <Text size="sm" c="green.8">
                      Выбран: <strong>{selectedPipelineName}</strong>
                    </Text>
                  </Card>
                )}
              </>
            )}

            <Group justify="flex-end" mt="md">
              <Button
                disabled={selectedPipelineId === null}
                onClick={() => setStep(1)}
              >
                Далее
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Маппинг" description="Настройка колонок">
          <Stack gap="md" mt="md">
            <TextInput
              label="Название маппинга"
              placeholder="Прайс-лист основной"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              required
            />

            <Autocomplete
              label="Колонка с SKU поставщика"
              description="Имя колонки в выводе пайплайна"
              placeholder="sku"
              data={availableColumns}
              value={skuColumn}
              onChange={setSkuColumn}
              required
            />

            <Autocomplete
              label="Колонка с названием товара"
              description="Имя колонки в выводе пайплайна"
              placeholder="name"
              data={availableColumns}
              value={nameColumn}
              onChange={setNameColumn}
              required
            />

            <TagsInput
              label="Variable-колонки"
              description="Колонки, которые меняются между прайс-листами (напр. price, stock)"
              placeholder="Добавьте колонку"
              data={availableColumns}
              value={variableColumns}
              onChange={setVariableColumns}
            />

            <NumberInput
              label="Порог автоматического матчинга"
              description="От 0 до 1. Позиции выше порога матчатся автоматически"
              value={threshold}
              onChange={(v) => setThreshold(Number(v))}
              min={0}
              max={1}
              step={0.01}
              decimalScale={2}
            />

            <NumberInput
              label="Нижний порог совпадения"
              description="От 0 до 1. Позиции ниже порога игнорируются"
              value={lowMatchThreshold}
              onChange={(v) => { if (typeof v === 'number') setLowMatchThreshold(v); }}
              min={0.1}
              max={0.99}
              step={0.01}
              decimalScale={2}
            />

            <Group justify="space-between" mt="md">
              <Button variant="default" onClick={() => setStep(0)}>
                Назад
              </Button>
              <Button
                loading={createMutation.isPending}
                disabled={!canSubmit}
                onClick={() => createMutation.mutate()}
              >
                Создать
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>
      </Stepper>

      <NewPipelineDrawer
        key={drawerKey}
        opened={drawerOpened}
        onClose={closeDrawer}
        onCreated={handlePipelineCreated}
      />
    </Stack>
  );
}
