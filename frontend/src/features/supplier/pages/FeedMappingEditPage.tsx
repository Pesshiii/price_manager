import {
  Anchor,
  Autocomplete,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  NumberInput,
  Select,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconEdit } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { listPipelines } from '@/features/dataframe/api';
import { dataframeKeys } from '@/features/dataframe/queryKeys';
import type { DataframePayload } from '@/features/dataframe/types';
import { FeedColumnMappingSection } from '../components/FeedColumnMappingSection';
import { NewPipelineDrawer } from '../components/NewPipelineDrawer';
import { getFeedMapping, updateFeedMapping } from '../api';
import { supplierKeys } from '../queryKeys';

export function FeedMappingEditPage() {
  const { id, mappingId } = useParams<{ id: string; mappingId: string }>();
  const supplierId = Number(id);
  const feedMappingId = Number(mappingId);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [name, setName] = useState('');
  const [pipelineId, setPipelineId] = useState<number | null>(null);
  const [pipelineName, setPipelineName] = useState('');
  const [skuColumn, setSkuColumn] = useState('');
  const [identityColumns, setIdentityColumns] = useState<string[]>([]);
  const [variableColumns, setVariableColumns] = useState<string[]>([]);
  const [threshold, setThreshold] = useState<number>(0.92);
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);

  // Pipeline picker modal + new pipeline drawer
  const [pickerOpened, { open: openPicker, close: closePicker }] = useDisclosure(false);
  const [drawerOpened, { open: openDrawer, close: closeDrawer }] = useDisclosure(false);
  const [drawerKey, setDrawerKey] = useState(0);
  const [pickerPipelineId, setPickerPipelineId] = useState<string | null>(null);

  const mappingQuery = useQuery({
    queryKey: supplierKeys.mapping(feedMappingId),
    queryFn: () => getFeedMapping(feedMappingId),
  });

  const pipelinesQuery = useQuery({
    queryKey: dataframeKeys.pipelines(),
    queryFn: listPipelines,
  });

  useEffect(() => {
    if (mappingQuery.data) {
      const m = mappingQuery.data;
      setName(m.name);
      setPipelineId(m.dataframe);
      setPipelineName(m.dataframe_detail.name);
      setSkuColumn(m.supplier_sku_column);
      setIdentityColumns(m.identity_columns);
      setVariableColumns(m.variable_columns);
      setThreshold(m.auto_match_threshold);
    }
  }, [mappingQuery.data]);

  const updateMutation = useMutation({
    mutationFn: () =>
      updateFeedMapping(feedMappingId, {
        supplier: supplierId,
        name: name.trim(),
        dataframe: pipelineId!,
        supplier_sku_column: skuColumn.trim(),
        identity_columns: identityColumns,
        variable_columns: variableColumns,
        auto_match_threshold: threshold,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: supplierKeys.mappings(supplierId) });
      qc.invalidateQueries({ queryKey: supplierKeys.mapping(feedMappingId) });
      notifications.show({ message: 'Маппинг обновлён', color: 'green' });
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

  const handlePickerConfirm = () => {
    if (!pickerPipelineId) return;
    const pipeline = pipelinesQuery.data?.find((p) => p.id === Number(pickerPipelineId));
    if (!pipeline) return;
    setPipelineId(pipeline.id);
    setPipelineName(pipeline.name);
    setAvailableColumns([]);
    setPickerPipelineId(null);
    closePicker();
  };

  const handleOpenNewPipeline = () => {
    closePicker();
    setDrawerKey((k) => k + 1);
    openDrawer();
  };

  const handlePipelineCreated = (pipeline: DataframePayload, previewColumns: string[]) => {
    setPipelineId(pipeline.id);
    setPipelineName(pipeline.name);
    setAvailableColumns(previewColumns);
  };

  const canSubmit =
    name.trim().length > 0 &&
    pipelineId !== null &&
    skuColumn.trim().length > 0 &&
    identityColumns.length > 0;

  if (mappingQuery.isLoading) return <Loader />;

  const pipelineData = (pipelinesQuery.data ?? []).map((p) => ({
    value: String(p.id),
    label: p.name,
  }));

  return (
    <Stack>
      <Group>
        <Anchor component={Link} to={`/suppliers/${supplierId}`} size="sm" c="dimmed">
          ← Поставщик
        </Anchor>
      </Group>

      <Title order={2}>Редактировать маппинг</Title>

      <Stack gap="md" maw={600}>
        <TextInput
          label="Название маппинга"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
        />

        <div>
          <Text size="sm" fw={500} mb={4}>
            Пайплайн
          </Text>
          <Card withBorder padding="sm">
            <Group justify="space-between">
              <Text size="sm">{pipelineName || '—'}</Text>
              <Button
                variant="subtle"
                size="xs"
                leftSection={<IconEdit size={14} />}
                onClick={openPicker}
              >
                Изменить
              </Button>
            </Group>
          </Card>
        </div>

        <Autocomplete
          label="Колонка с SKU поставщика"
          description="Имя колонки в выводе пайплайна"
          placeholder="sku"
          data={availableColumns}
          value={skuColumn}
          onChange={setSkuColumn}
          required
        />

        <TagsInput
          label="Identity-колонки"
          description="Колонки, однозначно идентифицирующие позицию (напр. sku, name)"
          placeholder="Добавьте колонку"
          data={availableColumns}
          value={identityColumns}
          onChange={setIdentityColumns}
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
          description="От 0 до 1"
          value={threshold}
          onChange={(v) => setThreshold(Number(v))}
          min={0}
          max={1}
          step={0.01}
          decimalScale={2}
        />

        <Group justify="space-between" mt="md">
          <Button variant="default" onClick={() => navigate(`/suppliers/${supplierId}`)}>
            Отмена
          </Button>
          <Button
            loading={updateMutation.isPending}
            disabled={!canSubmit}
            onClick={() => updateMutation.mutate()}
          >
            Сохранить
          </Button>
        </Group>

        <FeedColumnMappingSection
          mappingId={feedMappingId}
          availableColumns={availableColumns.length > 0 ? availableColumns : variableColumns}
        />
      </Stack>

      {/* Pipeline picker modal */}
      <Modal opened={pickerOpened} onClose={closePicker} title="Изменить пайплайн">
        <Stack gap="md">
          <Select
            label="Выберите пайплайн"
            placeholder="Поиск..."
            data={pipelineData}
            searchable
            clearable
            value={pickerPipelineId}
            onChange={setPickerPipelineId}
          />
          <Button
            variant="subtle"
            size="sm"
            onClick={handleOpenNewPipeline}
          >
            + Создать новый пайплайн
          </Button>
          <Group justify="flex-end">
            <Button variant="default" onClick={closePicker}>
              Отмена
            </Button>
            <Button disabled={!pickerPipelineId} onClick={handlePickerConfirm}>
              Выбрать
            </Button>
          </Group>
        </Stack>
      </Modal>

      <NewPipelineDrawer
        key={drawerKey}
        opened={drawerOpened}
        onClose={closeDrawer}
        onCreated={handlePipelineCreated}
      />
    </Stack>
  );
}
