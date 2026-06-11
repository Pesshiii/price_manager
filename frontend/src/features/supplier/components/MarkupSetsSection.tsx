import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { deleteMarkupSet, listMarkupSets } from '../api';
import { supplierKeys } from '../queryKeys';
import type { FeedMarkupSet } from '../types';
import { MarkupSetModal } from './MarkupSetModal';

interface Props {
  mappingId: number;
  availableColumns: string[];
}

export function MarkupSetsSection({ mappingId, availableColumns }: Props) {
  const qc = useQueryClient();
  const [modalOpened, { open: openModal, close: closeModal }] = useDisclosure(false);
  const [editing, setEditing] = useState<FeedMarkupSet | undefined>(undefined);

  const setsQuery = useQuery({
    queryKey: supplierKeys.markupSets(mappingId),
    queryFn: () => listMarkupSets(mappingId),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteMarkupSet,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: supplierKeys.markupSets(mappingId) });
      notifications.show({ message: 'Набор наценок удалён', color: 'green' });
    },
    onError: () => {
      notifications.show({ message: 'Не удалось удалить набор', color: 'red' });
    },
  });

  const handleAdd = () => {
    setEditing(undefined);
    openModal();
  };

  const handleEdit = (set: FeedMarkupSet) => {
    setEditing(set);
    openModal();
  };

  const handleClose = () => {
    closeModal();
    setEditing(undefined);
  };

  return (
    <>
      <Divider label="Наценки" labelPosition="left" mt="xl" />

      <Stack gap="sm">
        {setsQuery.isLoading && <Loader size="sm" />}

        {setsQuery.data?.map((set) => (
          <Card key={set.id} withBorder padding="sm">
            <Group justify="space-between" wrap="nowrap">
              <Stack gap={4}>
                <Group gap="xs">
                  <Text size="sm" fw={500}>
                    {set.name}
                  </Text>
                  <Badge size="xs" variant="light">
                    {set.rules.length} правил
                  </Badge>
                </Group>
                <Text size="xs" c="dimmed">
                  {set.price_column} → {set.output_column}
                </Text>
              </Stack>
              <Group gap="xs" wrap="nowrap">
                <ActionIcon variant="subtle" onClick={() => handleEdit(set)}>
                  <IconEdit size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  loading={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate(set.id)}
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            </Group>
          </Card>
        ))}

        {setsQuery.data?.length === 0 && (
          <Text size="sm" c="dimmed">
            Нет наборов наценок. Наценки применяются к матченым записям при переходе фида в «Готово».
          </Text>
        )}

        <Button
          variant="subtle"
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={handleAdd}
          w="fit-content"
        >
          Добавить набор наценок
        </Button>
      </Stack>

      <MarkupSetModal
        opened={modalOpened}
        onClose={handleClose}
        mappingId={mappingId}
        availableColumns={availableColumns}
        existing={editing}
      />
    </>
  );
}
