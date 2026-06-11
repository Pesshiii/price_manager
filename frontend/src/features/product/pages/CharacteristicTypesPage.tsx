import {
  ActionIcon,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  Modal,
  MultiSelect,
  SegmentedControl,
  Select,
  Stack,
  TagsInput,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useDebouncedValue, useDisclosure } from '@mantine/hooks';
import { IconEdit, IconEye, IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import {
  createCharacteristicType,
  deleteCharacteristicType,
  type CharacteristicTypeWritePayload,
  type ListCharTypesParams,
} from '../api';
import { CharacteristicTypeDetailModal } from '../components/CharacteristicTypeDetailModal';
import { CharacteristicTypeEditModal } from '../components/CharacteristicTypeEditModal';
import { useCategories } from '../hooks/useCategories';
import { useCharacteristicTypes } from '../hooks/useCharacteristicTypes';
import { charTypeKeys } from '../queryKeys';
import type { CharacteristicType, ValueType } from '../types';

const VALUE_TYPES: ValueType[] = ['string', 'integer', 'float', 'boolean', 'choice'];

const REQUIRED_OPTIONS = [
  { label: 'Все', value: 'all' },
  { label: 'Да', value: 'yes' },
  { label: 'Нет', value: 'no' },
];

interface FormState {
  name: string;
  label: string;
  value_type: ValueType;
  options: string[];
  unit: string;
  required: boolean;
  categories: number[];
}

const emptyForm: FormState = {
  name: '',
  label: '',
  value_type: 'string',
  options: [],
  unit: '',
  required: false,
  categories: [],
};

export function CharacteristicTypesPage() {
  const qc = useQueryClient();

  // ---- Filter state -------------------------------------------------------
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 300);
  const [categoryFilter, setCategoryFilter] = useState<string[]>([]);
  const [valueTypeFilter, setValueTypeFilter] = useState<ValueType | ''>('');
  const [requiredFilter, setRequiredFilter] = useState<'all' | 'yes' | 'no'>('all');

  const listParams = useMemo<ListCharTypesParams>(() => {
    const p: ListCharTypesParams = { page_size: 2000 };
    if (debouncedSearch.trim()) p.search = debouncedSearch.trim();
    if (categoryFilter.length > 0) p.category = categoryFilter.map(Number);
    if (valueTypeFilter) p.value_type = valueTypeFilter as ValueType;
    if (requiredFilter !== 'all') p.required = requiredFilter === 'yes';
    return p;
  }, [debouncedSearch, categoryFilter, valueTypeFilter, requiredFilter]);

  const { data: page, isLoading } = useCharacteristicTypes(listParams);
  const data = page?.results ?? [];
  const { data: categories } = useCategories();

  // ---- Create modal -------------------------------------------------------
  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [form, setForm] = useState<FormState>(emptyForm);

  const createMutation = useMutation({
    mutationFn: (payload: CharacteristicTypeWritePayload) =>
      createCharacteristicType(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: charTypeKeys.all });
      closeCreate();
      setForm(emptyForm);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCharacteristicType,
    onSuccess: () => qc.invalidateQueries({ queryKey: charTypeKeys.all }),
  });

  // ---- View + Edit modals -------------------------------------------------
  const [detailTarget, setDetailTarget] = useState<CharacteristicType | null>(null);
  const [editTarget, setEditTarget] = useState<CharacteristicType | null>(null);

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Типы характеристик</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={openCreate}>
          Новый тип
        </Button>
      </Group>

      {/* ---- Filter toolbar ------------------------------------------------ */}
      <Card withBorder>
        <Group grow align="end">
          <TextInput
            label="Поиск"
            placeholder="по имени или метке"
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            aria-label="Поиск"
          />
          <MultiSelect
            label="Категории"
            searchable
            clearable
            data={(categories ?? []).map((c) => ({
              value: String(c.id),
              label: '— '.repeat(c.level) + c.name,
            }))}
            value={categoryFilter}
            onChange={setCategoryFilter}
          />
          <Select
            label="Тип значения"
            placeholder="Любой"
            data={VALUE_TYPES}
            value={valueTypeFilter || null}
            onChange={(v) => setValueTypeFilter((v ?? '') as ValueType | '')}
            clearable
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Обязательная
            </Text>
            <SegmentedControl
              data={REQUIRED_OPTIONS}
              value={requiredFilter}
              onChange={(v) => setRequiredFilter(v as 'all' | 'yes' | 'no')}
            />
          </Stack>
        </Group>
      </Card>

      {isLoading && <Loader />}
      {!isLoading && (
        <Card withBorder padding={0}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Имя</Table.Th>
                <Table.Th>Метка</Table.Th>
                <Table.Th>Тип</Table.Th>
                <Table.Th>Ед.</Table.Th>
                <Table.Th>Обяз.</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.map((t) => (
                <Table.Tr key={t.id}>
                  <Table.Td>{t.name}</Table.Td>
                  <Table.Td>{t.label}</Table.Td>
                  <Table.Td>{t.value_type}</Table.Td>
                  <Table.Td>{t.unit || '—'}</Table.Td>
                  <Table.Td>{t.required ? 'да' : ''}</Table.Td>
                  <Table.Td>
                    <Group justify="flex-end" gap="xs">
                      <ActionIcon
                        variant="subtle"
                        onClick={() => setDetailTarget(t)}
                        aria-label="Просмотр"
                      >
                        <IconEye size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        onClick={() => setEditTarget(t)}
                        aria-label="Редактировать"
                      >
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        loading={deleteMutation.variables === t.id}
                        onClick={() => {
                          if (confirm(`Удалить «${t.label}»?`)) deleteMutation.mutate(t.id);
                        }}
                        aria-label="Удалить"
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      <CharacteristicTypeDetailModal
        opened={detailTarget != null}
        onClose={() => setDetailTarget(null)}
        type={detailTarget}
      />

      <CharacteristicTypeEditModal
        opened={editTarget != null}
        onClose={() => setEditTarget(null)}
        type={editTarget}
      />

      <Modal opened={createOpened} onClose={closeCreate} title="Новый тип характеристики" size="lg">
        <Stack>
          <Group grow>
            <TextInput
              label="Имя (slug)"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
              required
            />
            <TextInput
              label="Метка"
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.currentTarget.value })}
              required
            />
          </Group>
          <Group grow>
            <Select
              label="Тип значения"
              data={VALUE_TYPES}
              value={form.value_type}
              onChange={(v) => setForm({ ...form, value_type: (v ?? 'string') as ValueType })}
            />
            <TextInput
              label="Единица"
              value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.currentTarget.value })}
            />
          </Group>
          {form.value_type === 'choice' && (
            <TagsInput
              label="Варианты"
              value={form.options}
              onChange={(options) => setForm({ ...form, options })}
            />
          )}
          <MultiSelect
            label="Категории"
            searchable
            data={(categories ?? []).map((c) => ({
              value: String(c.id),
              label: '— '.repeat(c.level) + c.name,
            }))}
            value={form.categories.map(String)}
            onChange={(values) =>
              setForm({ ...form, categories: values.map((v) => Number(v)) })
            }
          />
          <Checkbox
            label="Обязательный"
            checked={form.required}
            onChange={(e) => setForm({ ...form, required: e.currentTarget.checked })}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={closeCreate}>
              Отмена
            </Button>
            <Button
              loading={createMutation.isPending}
              disabled={!form.name.trim() || !form.label.trim()}
              onClick={() =>
                createMutation.mutate({
                  name: form.name.trim(),
                  label: form.label.trim(),
                  value_type: form.value_type,
                  options: form.options,
                  unit: form.unit,
                  required: form.required,
                  categories: form.categories,
                })
              }
            >
              Создать
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
