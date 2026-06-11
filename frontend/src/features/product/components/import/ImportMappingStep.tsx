import {
  Autocomplete,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Switch,
  Table,
  TagsInput,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { createCharacteristicType } from '../../api';
import { useCharacteristicTypes } from '../../hooks/useCharacteristicTypes';
import { charTypeKeys } from '../../queryKeys';
import type {
  CategoryFieldMapping,
  CharacteristicType,
  DynamicCharSpec,
  FieldMapping,
  ImportMapping,
  ValueType,
} from '../../types';

const PRODUCT_FIELDS: Array<{ key: keyof ImportMapping; label: string; required?: boolean }> = [
  { key: 'sku', label: 'SKU', required: true },
  { key: 'name', label: 'Название', required: true },
  { key: 'category', label: 'Категория' },
  { key: 'brand', label: 'Бренд' },
  { key: 'description', label: 'Описание' },
  { key: 'status', label: 'Статус' },
];

const VALUE_TYPES: Array<{ value: ValueType; label: string }> = [
  { value: 'string', label: 'Строка' },
  { value: 'integer', label: 'Целое число' },
  { value: 'float', label: 'Число' },
  { value: 'boolean', label: 'Да/Нет' },
  { value: 'choice', label: 'Выбор из списка' },
];

export interface ImportMappingStepProps {
  columns: string[];
  /**
   * Metadata for characteristics the parent already knows about (e.g. resolved
   * from a saved mapping). The component does NOT use this list to enumerate
   * pickable types — that comes from a paginated `?search=` API call. Keep
   * this prop tiny (typically just the already-bound names) to avoid the
   * 10k-types-freeze-the-browser failure mode that the old "render every
   * type as a row" UI had.
   */
  characteristicTypes: CharacteristicType[];
  mapping: ImportMapping;
  onChange: (mapping: ImportMapping) => void;
}

function getColumn(value: FieldMapping | undefined): string | null {
  if (value && 'column' in value) return value.column;
  return null;
}

function getCategoryColumn(value: CategoryFieldMapping | undefined): string | null {
  if (value && 'column' in value) return value.column;
  return null;
}

export function ImportMappingStep({
  columns,
  characteristicTypes,
  mapping,
  onChange,
}: ImportMappingStepProps) {
  const qc = useQueryClient();
  const [modalOpened, { open: openModal, close: closeModal }] = useDisclosure(false);
  const [form, setForm] = useState({
    name: '',
    label: '',
    value_type: 'string' as ValueType,
    options: [] as string[],
    unit: '',
    required: false,
  });
  const [pickerQuery, setPickerQuery] = useState('');

  const createMutation = useMutation({
    mutationFn: createCharacteristicType,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: charTypeKeys.all });
      notifications.show({
        message: `Характеристика «${created.label}» создана`,
        color: 'green',
      });
      // Bind the newly-created type automatically so the user can pick a column.
      const chars = { ...(mapping.characteristics ?? {}) };
      if (!chars[created.name]) {
        chars[created.name] = { column: '' };
        onChange({ ...mapping, characteristics: chars });
      }
      closeModal();
      setForm({ name: '', label: '', value_type: 'string', options: [], unit: '', required: false });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: unknown } })?.response?.data ?? e;
      notifications.show({
        message: typeof msg === 'string' ? msg : JSON.stringify(msg),
        color: 'red',
      });
    },
  });

  // Search picker: paginated, bounded result set. Fires only when user types.
  const pickerEnabled = pickerQuery.trim().length > 0;
  const pickerQ = useCharacteristicTypes(
    pickerEnabled ? { search: pickerQuery.trim(), page_size: 20 } : {},
  );
  const pickerResults = pickerEnabled ? pickerQ.data?.results ?? [] : [];

  const charTypeIndex = useMemo(() => {
    const m = new Map<string, CharacteristicType>();
    for (const t of characteristicTypes) m.set(t.name, t);
    for (const t of pickerResults) m.set(t.name, t);
    return m;
  }, [characteristicTypes, pickerResults]);

  const setField = (key: keyof ImportMapping, column: string | null) => {
    const next: ImportMapping = { ...mapping };
    if (column) {
      (next[key] as FieldMapping) = { column };
    } else {
      delete next[key];
    }
    onChange(next);
  };

  const setCategoryColumn = (column: string | null) => {
    if (!column) {
      const { category: _drop, ...rest } = mapping;
      onChange(rest);
      return;
    }
    const prev = mapping.category;
    const prevCol = prev && 'column' in prev ? prev : undefined;
    onChange({
      ...mapping,
      category: {
        column,
        ...(prevCol?.path_separator !== undefined ? { path_separator: prevCol.path_separator } : {}),
      },
    });
  };

  const setCategoryOption = (patch: Partial<{ path_separator: string }>) => {
    const cat = mapping.category;
    if (!cat || !('column' in cat)) return;
    onChange({ ...mapping, category: { ...cat, ...patch } });
  };

  const setCharacteristic = (name: string, column: string | null) => {
    const chars = { ...(mapping.characteristics ?? {}) };
    if (column) {
      chars[name] = { column };
    } else {
      delete chars[name];
    }
    onChange({ ...mapping, characteristics: chars });
  };

  const bindNewCharacteristic = (name: string) => {
    if (!name) return;
    const chars = { ...(mapping.characteristics ?? {}) };
    if (!chars[name]) chars[name] = { column: '' };
    onChange({ ...mapping, characteristics: chars });
  };

  const dynamicSpecs: DynamicCharSpec[] = mapping.dynamic_characteristics ?? [];

  const updateDynamic = (idx: number, patch: Partial<DynamicCharSpec>) => {
    const next = dynamicSpecs.map((spec, i) => (i === idx ? { ...spec, ...patch } : spec));
    onChange({ ...mapping, dynamic_characteristics: next });
  };

  const removeDynamic = (idx: number) => {
    const next = dynamicSpecs.filter((_, i) => i !== idx);
    if (next.length === 0) {
      const { dynamic_characteristics: _drop, ...rest } = mapping;
      onChange(rest);
    } else {
      onChange({ ...mapping, dynamic_characteristics: next });
    }
  };

  const addDynamic = () => {
    onChange({
      ...mapping,
      dynamic_characteristics: [...dynamicSpecs, { name_column: '', value_column: '' }],
    });
  };

  const canSubmit =
    form.name.trim().length > 0 &&
    form.label.trim().length > 0 &&
    (form.value_type !== 'choice' || form.options.length > 0);

  const boundNames = Object.keys(mapping.characteristics ?? {});

  // Autocomplete `data` accepts `{value, label}` — show label so users can
  // search by it. Limit to top 20 (already bounded by ?page_size=20 above).
  const autocompleteData = pickerResults
    .filter((t) => !(mapping.characteristics ?? {})[t.name])
    .map((t) => ({ value: t.name, label: `${t.label} (${t.name})` }));

  return (
    <Stack>
      <Title order={4}>Поля продукта</Title>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Поле</Table.Th>
            <Table.Th>Колонка</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {PRODUCT_FIELDS.map((field) => (
            <Table.Tr key={field.key}>
              <Table.Td>
                <Text>
                  {field.label}
                  {field.required ? ' *' : ''}
                </Text>
              </Table.Td>
              <Table.Td>
                {field.key === 'category' ? (
                  <Stack gap="xs">
                    <Select
                      placeholder="—"
                      data={columns}
                      value={getCategoryColumn(mapping.category)}
                      onChange={setCategoryColumn}
                      clearable
                      searchable
                    />
                    {getCategoryColumn(mapping.category) && (
                      <TextInput
                        size="xs"
                        label="Разделитель"
                        placeholder=">"
                        value={
                          mapping.category && 'column' in mapping.category
                            ? (mapping.category.path_separator ?? '')
                            : ''
                        }
                        onChange={(e) =>
                          setCategoryOption({
                            path_separator: e.currentTarget.value || undefined,
                          })
                        }
                        style={{ width: 120 }}
                      />
                    )}
                  </Stack>
                ) : (
                  <Select
                    placeholder="—"
                    data={columns}
                    value={getColumn(mapping[field.key] as FieldMapping | undefined)}
                    onChange={(v) => setField(field.key, v)}
                    clearable
                    searchable
                  />
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      <Group justify="space-between" align="end">
        <Title order={4}>Характеристики</Title>
        <Group gap="xs">
          <Button
            variant="default"
            size="xs"
            leftSection={<IconPlus size={14} />}
            onClick={addDynamic}
          >
            Добавить вариант
          </Button>
          <Button
            variant="light"
            size="xs"
            leftSection={<IconPlus size={14} />}
            onClick={openModal}
          >
            Создать характеристику
          </Button>
        </Group>
      </Group>
      <Text c="dimmed" size="xs">
        Введите название известной характеристики чтобы привязать её к колонке.
        «Вариант» — это группа из трёх колонок (Имя / Значение / Единица), когда
        несколько характеристик хранятся в одних и тех же столбцах файла.
      </Text>
      <Autocomplete
        label="Привязать характеристику"
        placeholder="Начните печатать название…"
        data={autocompleteData}
        value={pickerQuery}
        onChange={setPickerQuery}
        onOptionSubmit={(value) => {
          bindNewCharacteristic(value);
          setPickerQuery('');
        }}
        limit={20}
      />
      {boundNames.length === 0 && dynamicSpecs.length === 0 ? (
        <Text c="dimmed" size="sm">
          Пока не привязано ни одной характеристики. Используйте поле выше, чтобы
          добавить нужные, или «Добавить вариант» для EAV-лайаута.
        </Text>
      ) : (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Характеристика</Table.Th>
              <Table.Th>Колонка значения</Table.Th>
              <Table.Th>Единица</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {boundNames.map((name) => {
              const type = charTypeIndex.get(name);
              return (
                <Table.Tr key={`bound-${name}`}>
                  <Table.Td>
                    <Text>
                      {type?.label ?? name}
                      {type?.required ? ' *' : ''}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Select
                      placeholder="—"
                      data={columns}
                      value={getColumn(mapping.characteristics?.[name])}
                      onChange={(v) => setCharacteristic(name, v)}
                      clearable
                      searchable
                    />
                  </Table.Td>
                  <Table.Td>
                    <Text c={type?.unit ? undefined : 'dimmed'} size="sm">
                      {type?.unit || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      variant="subtle"
                      color="red"
                      size="xs"
                      aria-label={`Отвязать ${type?.label ?? name}`}
                      onClick={() => setCharacteristic(name, null)}
                    >
                      <IconTrash size={14} />
                    </Button>
                  </Table.Td>
                </Table.Tr>
              );
            })}
            {dynamicSpecs.map((spec, idx) => (
              <Table.Tr key={`dynamic-${idx}`} data-testid={`dynamic-row-${idx}`}>
                <Table.Td>
                  <Select
                    placeholder="Имя из колонки"
                    aria-label={`Имя из колонки (группа ${idx + 1})`}
                    data={columns}
                    value={spec.name_column || null}
                    onChange={(v) => updateDynamic(idx, { name_column: v ?? '' })}
                    clearable
                    searchable
                  />
                </Table.Td>
                <Table.Td>
                  <Select
                    placeholder="Значение из колонки"
                    aria-label={`Значение из колонки (группа ${idx + 1})`}
                    data={columns}
                    value={spec.value_column || null}
                    onChange={(v) => updateDynamic(idx, { value_column: v ?? '' })}
                    clearable
                    searchable
                  />
                </Table.Td>
                <Table.Td>
                  <Select
                    placeholder="Единица из колонки"
                    aria-label={`Единица из колонки (группа ${idx + 1})`}
                    data={columns}
                    value={spec.unit_column || null}
                    onChange={(v) =>
                      updateDynamic(idx, { unit_column: v ?? undefined })
                    }
                    clearable
                    searchable
                  />
                </Table.Td>
                <Table.Td>
                  <Button
                    variant="subtle"
                    color="red"
                    size="xs"
                    aria-label={`Удалить группу ${idx + 1}`}
                    onClick={() => removeDynamic(idx)}
                  >
                    <IconTrash size={14} />
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal
        opened={modalOpened}
        onClose={closeModal}
        title="Создать характеристику"
      >
        <Stack>
          <TextInput
            label="Ключ (slug)"
            description="Латиница/цифры/-/_. По нему ссылается mapping."
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
            required
          />
          <TextInput
            label="Название"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.currentTarget.value })}
            required
          />
          <Select
            label="Тип значения"
            data={VALUE_TYPES}
            value={form.value_type}
            onChange={(v) => setForm({ ...form, value_type: (v as ValueType) ?? 'string' })}
          />
          {form.value_type === 'choice' && (
            <TagsInput
              label="Варианты"
              description="Введите и нажмите Enter"
              value={form.options}
              onChange={(opts) => setForm({ ...form, options: opts })}
            />
          )}
          <TextInput
            label="Единица измерения"
            value={form.unit}
            onChange={(e) => setForm({ ...form, unit: e.currentTarget.value })}
          />
          <Switch
            label="Обязательная"
            checked={form.required}
            onChange={(e) => setForm({ ...form, required: e.currentTarget.checked })}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={closeModal}>
              Отмена
            </Button>
            <Button
              loading={createMutation.isPending}
              disabled={!canSubmit}
              onClick={() =>
                createMutation.mutate({
                  name: form.name.trim(),
                  label: form.label.trim(),
                  value_type: form.value_type,
                  options: form.value_type === 'choice' ? form.options : undefined,
                  unit: form.unit || undefined,
                  required: form.required,
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
