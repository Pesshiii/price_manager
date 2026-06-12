import {
  ActionIcon,
  Autocomplete,
  Button,
  Divider,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCheck, IconEdit, IconTrash, IconX } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '@/api/client';
import {
  createColumnMapping,
  deleteColumnMapping,
  listColumnMappings,
  updateColumnMapping,
} from '../api';
import { supplierKeys } from '../queryKeys';
import type { FeedColumnMapping } from '../types';

interface Props {
  mappingId: number;
  availableColumns: string[];
}

interface SimplePriceType {
  id: number;
  name: string;
  label: string;
}

type EditingRow =
  | {
      type: 'new';
      column_name: string;
      role: 'price' | 'stock' | 'other';
      price_type: number | null;
    }
  | {
      type: 'existing';
      id: number;
      column_name: string;
      role: 'price' | 'stock' | 'other';
      price_type: number | null;
    }
  | null;

const ROLE_OPTIONS = [
  { value: 'price', label: 'Цена' },
  { value: 'stock', label: 'Остаток' },
  { value: 'other', label: 'Другое' },
];

export function FeedColumnMappingSection({ mappingId, availableColumns }: Props) {
  const qc = useQueryClient();
  const [editingRow, setEditingRow] = useState<EditingRow>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const columnMappingsQuery = useQuery({
    queryKey: supplierKeys.columnMappings(mappingId),
    queryFn: () => listColumnMappings(mappingId),
  });

  const priceTypesQuery = useQuery({
    queryKey: ['pricing', 'price-types'],
    queryFn: async () => {
      const { data } = await api.get<SimplePriceType[]>('/pricing/price-types/');
      return data;
    },
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!editingRow) return;
      const { column_name, role, price_type } = editingRow;
      if (editingRow.type === 'new') {
        await createColumnMapping(mappingId, { column_name, role, price_type });
      } else {
        await updateColumnMapping(mappingId, editingRow.id, { column_name, role, price_type });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: supplierKeys.columnMappings(mappingId) });
      setEditingRow(null);
      notifications.show({ message: 'Колонка сохранена', color: 'green' });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: unknown } })?.response?.data ?? e;
      notifications.show({
        message: typeof msg === 'string' ? msg : JSON.stringify(msg),
        color: 'red',
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => {
      setDeletingId(id);
      return deleteColumnMapping(mappingId, id);
    },
    onSuccess: () => {
      setDeletingId(null);
      qc.invalidateQueries({ queryKey: supplierKeys.columnMappings(mappingId) });
      notifications.show({ message: 'Колонка удалена', color: 'green' });
    },
    onError: () => {
      setDeletingId(null);
      notifications.show({ message: 'Не удалось удалить', color: 'red' });
    },
  });

  const handleEdit = (cm: FeedColumnMapping) => {
    setEditingRow({
      type: 'existing',
      id: cm.id,
      column_name: cm.column_name,
      role: cm.role,
      price_type: cm.price_type,
    });
  };

  const handleAddNew = () => {
    setEditingRow({ type: 'new', column_name: '', role: 'other', price_type: null });
  };

  const handleCancel = () => setEditingRow(null);

  const priceTypeOptions = (priceTypesQuery.data ?? []).map((pt) => ({
    value: String(pt.id),
    label: pt.label || pt.name,
  }));

  const rows = columnMappingsQuery.data ?? [];

  const roleLabelMap: Record<string, string> = {
    price: 'Цена',
    stock: 'Остаток',
    other: 'Другое',
  };

  return (
    <>
      <Divider label="Колонки" labelPosition="left" mt="xl" />

      {columnMappingsQuery.isLoading && <Loader size="sm" />}

      {!columnMappingsQuery.isLoading && rows.length === 0 && editingRow === null && (
        <Text size="sm" c="dimmed">
          Нет колонок
        </Text>
      )}

      {(rows.length > 0 || editingRow !== null) && (
        <Table withTableBorder withColumnBorders fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Колонка</Table.Th>
              <Table.Th>Роль</Table.Th>
              <Table.Th>Тип цены</Table.Th>
              <Table.Th w={80}>Действия</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((cm) => {
              const isEditing = editingRow?.type === 'existing' && editingRow.id === cm.id;

              if (isEditing && editingRow) {
                return (
                  <Table.Tr key={cm.id}>
                    <Table.Td>
                      <Autocomplete
                        size="xs"
                        data={availableColumns}
                        value={editingRow.column_name}
                        onChange={(val) =>
                          setEditingRow((prev) => prev && { ...prev, column_name: val })
                        }
                        placeholder="Колонка"
                      />
                    </Table.Td>
                    <Table.Td>
                      <Select
                        size="xs"
                        data={ROLE_OPTIONS}
                        value={editingRow.role}
                        onChange={(val) =>
                          setEditingRow(
                            (prev) =>
                              prev && {
                                ...prev,
                                role: (val as 'price' | 'stock' | 'other') ?? 'other',
                                price_type: val !== 'price' ? null : prev.price_type,
                              },
                          )
                        }
                      />
                    </Table.Td>
                    <Table.Td>
                      {editingRow.role === 'price' && (
                        <Select
                          size="xs"
                          data={priceTypeOptions}
                          value={editingRow.price_type !== null ? String(editingRow.price_type) : null}
                          onChange={(val) =>
                            setEditingRow(
                              (prev) =>
                                prev && { ...prev, price_type: val ? Number(val) : null },
                            )
                          }
                          placeholder="Тип цены"
                          clearable
                        />
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          color="green"
                          loading={saveMutation.isPending}
                          disabled={!editingRow?.column_name?.trim()}
                          onClick={() => saveMutation.mutate()}
                        >
                          <IconCheck size={14} />
                        </ActionIcon>
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          onClick={handleCancel}
                        >
                          <IconX size={14} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                );
              }

              const priceTypeName = cm.price_type
                ? (priceTypesQuery.data?.find((pt) => pt.id === cm.price_type)?.label ??
                  String(cm.price_type))
                : '—';

              return (
                <Table.Tr key={cm.id}>
                  <Table.Td>{cm.column_name}</Table.Td>
                  <Table.Td>{roleLabelMap[cm.role] ?? cm.role}</Table.Td>
                  <Table.Td>{cm.role === 'price' ? priceTypeName : '—'}</Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <ActionIcon
                        size="sm"
                        variant="subtle"
                        onClick={() => handleEdit(cm)}
                      >
                        <IconEdit size={14} />
                      </ActionIcon>
                      <ActionIcon
                        size="sm"
                        variant="subtle"
                        color="red"
                        loading={deletingId === cm.id}
                        onClick={() => {
                          if (window.confirm('Удалить колонку?')) {
                            deleteMutation.mutate(cm.id);
                          }
                        }}
                      >
                        <IconTrash size={14} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}

            {editingRow?.type === 'new' && (
              <Table.Tr>
                <Table.Td>
                  <Autocomplete
                    size="xs"
                    data={availableColumns}
                    value={editingRow.column_name}
                    onChange={(val) =>
                      setEditingRow((prev) => prev && { ...prev, column_name: val })
                    }
                    placeholder="Колонка"
                  />
                </Table.Td>
                <Table.Td>
                  <Select
                    size="xs"
                    data={ROLE_OPTIONS}
                    value={editingRow.role}
                    onChange={(val) =>
                      setEditingRow(
                        (prev) =>
                          prev && {
                            ...prev,
                            role: (val as 'price' | 'stock' | 'other') ?? 'other',
                            price_type: val !== 'price' ? null : prev.price_type,
                          },
                      )
                    }
                  />
                </Table.Td>
                <Table.Td>
                  {editingRow.role === 'price' && (
                    <Select
                      size="xs"
                      data={priceTypeOptions}
                      value={editingRow.price_type !== null ? String(editingRow.price_type) : null}
                      onChange={(val) =>
                        setEditingRow(
                          (prev) => prev && { ...prev, price_type: val ? Number(val) : null },
                        )
                      }
                      placeholder="Тип цены"
                      clearable
                    />
                  )}
                </Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      color="green"
                      loading={saveMutation.isPending}
                      disabled={!editingRow?.column_name?.trim()}
                      onClick={() => saveMutation.mutate()}
                    >
                      <IconCheck size={14} />
                    </ActionIcon>
                    <ActionIcon size="sm" variant="subtle" onClick={handleCancel}>
                      <IconX size={14} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}

      <Stack mt="xs">
        <Button
          variant="subtle"
          size="xs"
          w="fit-content"
          disabled={editingRow !== null}
          onClick={handleAddNew}
        >
          Добавить колонку
        </Button>
      </Stack>
    </>
  );
}
