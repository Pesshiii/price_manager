import {
  ActionIcon,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { IconPlus, IconTrash, IconEdit } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { deletePipeline, listPipelines } from '../api';
import { dataframeKeys } from '../queryKeys';

export function DataframeListPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: dataframeKeys.pipelines(),
    queryFn: listPipelines,
  });
  const removeMutation = useMutation({
    mutationFn: deletePipeline,
    onSuccess: () => qc.invalidateQueries({ queryKey: dataframeKeys.pipelines() }),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Dataframe</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => navigate('/dataframe/new')}
        >
          Новый пайплайн
        </Button>
      </Group>

      {isLoading && <Loader />}

      {!isLoading && (data?.length ?? 0) === 0 && (
        <Card withBorder padding="lg">
          <Stack align="center" gap="xs">
            <Text c="dimmed">Пока нет пайплайнов</Text>
            <Button
              variant="light"
              leftSection={<IconPlus size={16} />}
              onClick={() => navigate('/dataframe/new')}
            >
              Создать первый
            </Button>
          </Stack>
        </Card>
      )}

      {!isLoading && (data?.length ?? 0) > 0 && (
        <Card withBorder padding={0}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Название</Table.Th>
                <Table.Th>Reader</Table.Th>
                <Table.Th>Шагов</Table.Th>
                <Table.Th>Обновлён</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data!.map((p) => (
                <Table.Tr key={p.id}>
                  <Table.Td>
                    <Text component={Link} to={`/dataframe/${p.id}`} fw={500}>
                      {p.name}
                    </Text>
                  </Table.Td>
                  <Table.Td>{p.instructions.reader.func || '—'}</Table.Td>
                  <Table.Td>{p.instructions.transforms.length}</Table.Td>
                  <Table.Td>{new Date(p.updated_at).toLocaleString()}</Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <ActionIcon
                        variant="subtle"
                        component={Link}
                        to={`/dataframe/${p.id}`}
                        aria-label="Редактировать"
                      >
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        loading={
                          removeMutation.isPending && removeMutation.variables === p.id
                        }
                        onClick={() => {
                          if (confirm(`Удалить пайплайн «${p.name}»?`)) {
                            removeMutation.mutate(p.id);
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
    </Stack>
  );
}
