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
import { createPriceType, deletePriceType, listPriceTypes, updatePriceType } from '../api';
import { pricingKeys } from '../queryKeys';
import type { PriceType } from '../types';

interface CreateForm {
  name: string;
  label: string;
}

const emptyCreateForm: CreateForm = { name: '', label: '' };

export function PriceTypesPage() {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: pricingKeys.priceTypes(),
    queryFn: listPriceTypes,
  });

  // ---- Create modal -------------------------------------------------------
  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [createForm, setCreateForm] = useState<CreateForm>(emptyCreateForm);

  // Bug 3 fix: reset form on cancel so stale values don't persist on reopen
  function handleCloseCreate() {
    setCreateForm(emptyCreateForm);
    closeCreate();
  }

  const createMutation = useMutation({
    mutationFn: createPriceType,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pricingKeys.priceTypes() });
      handleCloseCreate();
    },
    onError: () => {
      notifications.show({ message: 'Не удалось создать тип цены', color: 'red' });
    },
  });

  // ---- Edit modal ---------------------------------------------------------
  const [editTarget, setEditTarget] = useState<PriceType | null>(null);
  const [editLabel, setEditLabel] = useState('');

  function openEdit(pt: PriceType) {
    setEditTarget(pt);
    setEditLabel(pt.label);
  }

  function closeEdit() {
    setEditTarget(null);
    setEditLabel('');
  }

  const updateMutation = useMutation({
    mutationFn: ({ id, label }: { id: number; label: string }) =>
      updatePriceType(id, { label }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pricingKeys.priceTypes() });
      closeEdit();
    },
    onError: () => {
      notifications.show({ message: 'Не удалось обновить тип цены', color: 'red' });
    },
  });

  // ---- Delete -------------------------------------------------------------
  const deleteMutation = useMutation({
    mutationFn: deletePriceType,
    onSuccess: () => qc.invalidateQueries({ queryKey: pricingKeys.priceTypes() }),
    onError: () => {
      notifications.show({ message: 'Не удалось удалить тип цены', color: 'red' });
    },
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Типы цен</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={openCreate}>
          Добавить
        </Button>
      </Group>

      {isLoading && <Loader />}

      {!isLoading && (data ?? []).length === 0 && (
        <Card withBorder padding="lg">
          <Stack align="center" gap="xs">
            <Text c="dimmed">Типы цен не добавлены</Text>
            <Button
              variant="light"
              leftSection={<IconPlus size={16} />}
              onClick={openCreate}
            >
              Добавить первый
            </Button>
          </Stack>
        </Card>
      )}

      {!isLoading && (data ?? []).length > 0 && (
        <Card withBorder padding={0}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Ключ</Table.Th>
                <Table.Th>Название</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(data ?? []).map((pt) => (
                <Table.Tr key={pt.id}>
                  <Table.Td>
                    <Text size="sm" c="dimmed" ff="monospace">
                      {pt.name}
                    </Text>
                  </Table.Td>
                  <Table.Td>{pt.label}</Table.Td>
                  <Table.Td>
                    <Group justify="flex-end" gap="xs">
                      <ActionIcon
                        variant="subtle"
                        onClick={() => openEdit(pt)}
                        aria-label="Редактировать"
                      >
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        loading={
                          deleteMutation.isPending && deleteMutation.variables === pt.id
                        }
                        onClick={() => {
                          if (confirm(`Удалить тип цены «${pt.label}»?`)) {
                            deleteMutation.mutate(pt.id);
                          }
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
      <Modal opened={createOpened} onClose={handleCloseCreate} title="Новый тип цены">
        <Stack>
          <TextInput
            label="Ключ (slug)"
            placeholder="retail_price"
            value={createForm.name}
            onChange={(e) => setCreateForm({ ...createForm, name: e.currentTarget.value })}
            required
            description="Ключ нельзя изменить после создания"
          />
          <TextInput
            label="Название"
            placeholder="Розничная цена"
            value={createForm.label}
            onChange={(e) => setCreateForm({ ...createForm, label: e.currentTarget.value })}
            required
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={handleCloseCreate}>
              Отмена
            </Button>
            <Button
              loading={createMutation.isPending}
              disabled={!createForm.name.trim() || !createForm.label.trim()}
              onClick={() =>
                createMutation.mutate({
                  name: createForm.name.trim(),
                  label: createForm.label.trim(),
                })
              }
            >
              Создать
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Edit label modal */}
      <Modal
        opened={editTarget != null}
        onClose={closeEdit}
        title="Редактировать название"
        size="sm"
      >
        <Stack>
          <TextInput
            label="Название"
            value={editLabel}
            onChange={(e) => setEditLabel(e.currentTarget.value)}
            required
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={closeEdit}>
              Отмена
            </Button>
            <Button
              loading={updateMutation.isPending}
              disabled={!editLabel.trim()}
              onClick={() => {
                if (editTarget) {
                  updateMutation.mutate({ id: editTarget.id, label: editLabel.trim() });
                }
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
