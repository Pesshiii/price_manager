import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  Title,
  UnstyledButton,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconChevronDown, IconChevronUp, IconEdit, IconPlus, IconSelector, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { createFeed, deleteFeedMapping, getSupplier, listFeedMappings, listFeeds } from '../api';
import { supplierKeys } from '../queryKeys';
import type { FeedMapping, SupplierFeedStatus } from '../types';

type MappingSortField = 'name' | 'pipeline' | 'sku_column' | 'threshold';
type SortDir = 'asc' | 'desc';

function sortMappings(
  mappings: FeedMapping[],
  field: MappingSortField,
  dir: SortDir,
): FeedMapping[] {
  return [...mappings].sort((a, b) => {
    let cmp = 0;
    if (field === 'name') cmp = a.name.localeCompare(b.name);
    else if (field === 'pipeline')
      cmp = a.dataframe_detail.name.localeCompare(b.dataframe_detail.name);
    else if (field === 'sku_column')
      cmp = a.supplier_sku_column.localeCompare(b.supplier_sku_column);
    else if (field === 'threshold') cmp = a.auto_match_threshold - b.auto_match_threshold;
    return dir === 'asc' ? cmp : -cmp;
  });
}

function SortTh({
  children,
  field,
  active,
  dir,
  onSort,
}: {
  children: React.ReactNode;
  field: MappingSortField;
  active: MappingSortField;
  dir: SortDir;
  onSort: (f: MappingSortField) => void;
}) {
  const isActive = active === field;
  const Icon = isActive ? (dir === 'asc' ? IconChevronUp : IconChevronDown) : IconSelector;
  return (
    <Table.Th>
      <UnstyledButton
        onClick={() => onSort(field)}
        style={{ display: 'flex', alignItems: 'center', gap: 4, fontWeight: 500 }}
      >
        {children}
        <Icon size={14} style={{ opacity: isActive ? 1 : 0.4 }} />
      </UnstyledButton>
    </Table.Th>
  );
}

const STATUS_COLOR: Record<SupplierFeedStatus, string> = {
  draft: 'gray',
  processing: 'blue',
  matched: 'green',
  partial: 'yellow',
  done: 'teal',
  error: 'red',
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('ru-RU');
}

export function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const supplierId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [modalOpen, { open: openModal, close: closeModal }] = useDisclosure(false);
  const [selectedMapping, setSelectedMapping] = useState<string | null>(null);
  const [sortField, setSortField] = useState<MappingSortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  function handleSort(field: MappingSortField) {
    if (field === sortField) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortField(field); setSortDir('asc'); }
  }

  const supplierQuery = useQuery({
    queryKey: supplierKeys.supplier(supplierId),
    queryFn: () => getSupplier(supplierId),
  });

  const mappingsQuery = useQuery({
    queryKey: supplierKeys.mappings(supplierId),
    queryFn: () => listFeedMappings(supplierId),
  });

  const feedsQuery = useQuery({
    queryKey: supplierKeys.feeds(supplierId),
    queryFn: () => listFeeds(supplierId),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteFeedMapping,
    onSuccess: () => qc.invalidateQueries({ queryKey: supplierKeys.mappings(supplierId) }),
    onError: (error: unknown) => {
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 409) {
        notifications.show({
          message: 'Нельзя удалить: маппинг используется в фидах.',
          color: 'red',
        });
      } else {
        notifications.show({ message: 'Не удалось удалить маппинг.', color: 'red' });
      }
    },
  });

  const createFeedMutation = useMutation({
    mutationFn: createFeed,
    onSuccess: (feed) => {
      closeModal();
      setSelectedMapping(null);
      navigate(`/suppliers/${supplierId}/feeds/${feed.id}`);
    },
    onError: () => {
      notifications.show({ message: 'Не удалось создать выгрузку.', color: 'red' });
    },
  });

  const isLoading = supplierQuery.isLoading || mappingsQuery.isLoading || feedsQuery.isLoading;

  const mappingOptions =
    mappingsQuery.data?.map((m) => ({ value: String(m.id), label: m.name })) ?? [];

  const mappingById = Object.fromEntries((mappingsQuery.data ?? []).map((m) => [m.id, m]));

  return (
    <Stack>
      <Group>
        <Anchor component={Link} to="/suppliers" size="sm" c="dimmed">
          ← Поставщики
        </Anchor>
      </Group>

      {supplierQuery.isLoading && <Loader />}

      {supplierQuery.data && (
        <Group justify="space-between">
          <Title order={2}>{supplierQuery.data.name}</Title>
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => navigate(`/suppliers/${supplierId}/mappings/new`)}
          >
            Добавить маппинг
          </Button>
        </Group>
      )}

      {!isLoading && (
        <Stack gap="xs">
          <Text fw={500}>Маппинги фидов</Text>

          {(mappingsQuery.data?.length ?? 0) === 0 ? (
            <Card withBorder padding="lg">
              <Stack align="center" gap="xs">
                <Text c="dimmed">Маппинги не добавлены</Text>
                <Button
                  variant="light"
                  leftSection={<IconPlus size={16} />}
                  onClick={() => navigate(`/suppliers/${supplierId}/mappings/new`)}
                >
                  Добавить первый
                </Button>
              </Stack>
            </Card>
          ) : (
            <Card withBorder padding={0}>
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <SortTh field="name" active={sortField} dir={sortDir} onSort={handleSort}>
                      Название
                    </SortTh>
                    <SortTh field="pipeline" active={sortField} dir={sortDir} onSort={handleSort}>
                      Пайплайн
                    </SortTh>
                    <SortTh field="sku_column" active={sortField} dir={sortDir} onSort={handleSort}>
                      SKU-колонка
                    </SortTh>
                    <SortTh field="threshold" active={sortField} dir={sortDir} onSort={handleSort}>
                      Порог
                    </SortTh>
                    <Table.Th />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {sortMappings(mappingsQuery.data!, sortField, sortDir).map((m) => (
                    <Table.Tr key={m.id}>
                      <Table.Td fw={500}>{m.name}</Table.Td>
                      <Table.Td>
                        <Text size="sm" c="dimmed">
                          {m.dataframe_detail.name}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge variant="light" color="blue" size="sm">
                          {m.supplier_sku_column}
                        </Badge>
                      </Table.Td>
                      <Table.Td>{m.auto_match_threshold}</Table.Td>
                      <Table.Td>
                        <Group justify="flex-end" gap="xs">
                          <ActionIcon
                            variant="subtle"
                            onClick={() =>
                              navigate(`/suppliers/${supplierId}/mappings/${m.id}/edit`)
                            }
                            aria-label="Редактировать"
                          >
                            <IconEdit size={16} />
                          </ActionIcon>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            loading={
                              deleteMutation.isPending && deleteMutation.variables === m.id
                            }
                            onClick={() => {
                              if (confirm(`Удалить маппинг «${m.name}»?`)) {
                                deleteMutation.mutate(m.id);
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
      )}

      {!isLoading && (
        <Stack gap="xs">
          <Group justify="space-between">
            <Text fw={500}>Выгрузки</Text>
            <Group gap="xs">
              <Button
                variant="light"
                onClick={() => navigate(`/suppliers/${supplierId}/links`)}
              >
                Управление связями
              </Button>
              <Button leftSection={<IconPlus size={16} />} onClick={openModal}>
                Новая выгрузка
              </Button>
            </Group>
          </Group>

          {(feedsQuery.data?.length ?? 0) === 0 ? (
            <Card withBorder padding="lg">
              <Text c="dimmed" ta="center">
                Выгрузки не созданы
              </Text>
            </Card>
          ) : (
            <Card withBorder padding={0}>
              <Table highlightOnHover style={{ cursor: 'pointer' }}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Дата создания</Table.Th>
                    <Table.Th>Маппинг</Table.Th>
                    <Table.Th>Статус</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {feedsQuery.data!.map((f) => (
                    <Table.Tr
                      key={f.id}
                      onClick={() => navigate(`/suppliers/${supplierId}/feeds/${f.id}`)}
                    >
                      <Table.Td>{formatDate(f.created_at)}</Table.Td>
                      <Table.Td>{mappingById[f.feed_mapping]?.name ?? f.feed_mapping}</Table.Td>
                      <Table.Td>
                        <Badge
                          variant="light"
                          color={STATUS_COLOR[f.status] ?? 'gray'}
                          size="sm"
                        >
                          {f.status}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
          )}
        </Stack>
      )}

      <Modal opened={modalOpen} onClose={closeModal} title="Новая выгрузка">
        <Stack>
          <Select
            label="Маппинг"
            placeholder="Выберите маппинг"
            data={mappingOptions}
            value={selectedMapping}
            onChange={setSelectedMapping}
            searchable
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={closeModal}>
              Отмена
            </Button>
            <Button
              disabled={!selectedMapping}
              loading={createFeedMutation.isPending}
              onClick={() => {
                if (selectedMapping) {
                  createFeedMutation.mutate({
                    supplier: supplierId,
                    feed_mapping: Number(selectedMapping),
                  });
                }
              }}
            >
              Создать
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
