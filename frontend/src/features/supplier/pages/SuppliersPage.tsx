import {
  ActionIcon,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { createSupplier, deleteSupplier, listSuppliers, updateSupplier } from '../api';
import { supplierKeys } from '../queryKeys';
import type { Supplier } from '../types';

export function SuppliersPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: supplierKeys.all,
    queryFn: listSuppliers,
  });

  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [editTarget, setEditTarget] = useState<Supplier | null>(null);
  const [name, setName] = useState('');

  function openEdit(supplier: Supplier) {
    setEditTarget(supplier);
    setName(supplier.name);
  }

  function closeEdit() {
    setEditTarget(null);
    setName('');
  }

  const createMutation = useMutation({
    mutationFn: createSupplier,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: supplierKeys.all });
      closeCreate();
      setName('');
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      updateSupplier(id, { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: supplierKeys.all });
      closeEdit();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSupplier,
    onSuccess: () => qc.invalidateQueries({ queryKey: supplierKeys.all }),
    onError: (error: unknown) => {
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 409) {
        notifications.show({
          message: 'Нельзя удалить: поставщик используется в фидах. Сначала удалите связанные фиды.',
          color: 'red',
        });
      } else {
        notifications.show({ message: 'Не удалось удалить поставщика.', color: 'red' });
      }
    },
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Поставщики</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => {
            setName('');
            openCreate();
          }}
        >
          Новый поставщик
        </Button>
      </Group>

      {isLoading && <Loader />}

      {!isLoading && (
        <Card withBorder padding={0}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Название</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(data ?? []).map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td>
                    <Text component={Link} to={`/suppliers/${s.id}`} fw={500}>
                      {s.name}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group justify="flex-end" gap="xs">
                      <ActionIcon
                        variant="subtle"
                        onClick={() => openEdit(s)}
                        aria-label="Редактировать"
                      >
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        loading={deleteMutation.variables === s.id && deleteMutation.isPending}
                        onClick={() => {
                          if (confirm(`Удалить «${s.name}»?`)) deleteMutation.mutate(s.id);
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

      {/* Create modal */}
      <Modal opened={createOpened} onClose={closeCreate} title="Новый поставщик">
        <Stack>
          <TextInput
            label="Название"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={closeCreate}>
              Отмена
            </Button>
            <Button
              loading={createMutation.isPending}
              disabled={!name.trim()}
              onClick={() => createMutation.mutate({ name: name.trim() })}
            >
              Создать
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Edit modal */}
      <Modal opened={editTarget !== null} onClose={closeEdit} title="Редактировать поставщика">
        <Stack>
          <TextInput
            label="Название"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={closeEdit}>
              Отмена
            </Button>
            <Button
              loading={updateMutation.isPending}
              disabled={!name.trim() || name.trim() === editTarget?.name}
              onClick={() => {
                if (editTarget) updateMutation.mutate({ id: editTarget.id, name: name.trim() });
              }}
            >
              Сохранить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
