import {
  ActionIcon,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  TextInput,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { createBrand, deleteBrand } from '../api';
import { useBrands } from '../hooks/useBrands';
import { brandKeys } from '../queryKeys';

export function BrandsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useBrands();
  const [opened, { open, close }] = useDisclosure(false);
  const [name, setName] = useState('');

  const createMutation = useMutation({
    mutationFn: createBrand,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: brandKeys.all });
      close();
      setName('');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteBrand,
    onSuccess: () => qc.invalidateQueries({ queryKey: brandKeys.all }),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Бренды</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={open}>
          Новый бренд
        </Button>
      </Group>
      {isLoading && <Loader />}
      {!isLoading && (
        <Card withBorder padding={0}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Название</Table.Th>
                <Table.Th>Slug</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(data ?? []).map((b) => (
                <Table.Tr key={b.id}>
                  <Table.Td>{b.name}</Table.Td>
                  <Table.Td>{b.slug}</Table.Td>
                  <Table.Td>
                    <Group justify="flex-end">
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        loading={deleteMutation.variables === b.id}
                        onClick={() => {
                          if (confirm(`Удалить «${b.name}»?`)) deleteMutation.mutate(b.id);
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
      <Modal opened={opened} onClose={close} title="Новый бренд">
        <Stack>
          <TextInput
            label="Название"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
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
    </Stack>
  );
}
