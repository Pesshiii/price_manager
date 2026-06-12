import {
  ActionIcon,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  MultiSelect,
  Pagination,
  Popover,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useDebouncedValue, useDisclosure } from '@mantine/hooks';
import { IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  addCategoryCharType,
  assignProducts,
  getCategoryCharTypeUsage,
  getCategory,
  listCharacteristicTypes,
  listUnassignedProducts,
  removeCategoryCharType,
} from '../api';
import { categoryKeys, charTypeKeys, productKeys } from '../queryKeys';
import type { CharacteristicType } from '../types';

const PAGE_SIZE = 20;

export function CategoryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const categoryId = Number(id);
  const qc = useQueryClient();

  const [pickerSearch, setPickerSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(pickerSearch, 300);

  const [productSearch, setProductSearch] = useState('');
  const [debouncedProductSearch] = useDebouncedValue(productSearch, 300);
  const [productPage, setProductPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const categoryQuery = useQuery({
    queryKey: categoryKeys.detail(categoryId),
    queryFn: () => getCategory(categoryId),
  });

  const linkedTypesQuery = useQuery({
    queryKey: charTypeKeys.list({ category: categoryId }),
    queryFn: () => listCharacteristicTypes({ category: categoryId }),
  });

  const searchTypesQuery = useQuery({
    queryKey: charTypeKeys.list({ search: debouncedSearch }),
    queryFn: () => listCharacteristicTypes({ search: debouncedSearch }),
    enabled: debouncedSearch.length > 0,
  });

  const unassignedQuery = useQuery({
    queryKey: [...productKeys.all, 'unassigned', debouncedProductSearch, productPage],
    queryFn: () =>
      listUnassignedProducts({ q: debouncedProductSearch, page: productPage, page_size: PAGE_SIZE }),
  });

  const linkedIds = new Set((linkedTypesQuery.data?.results ?? []).map((ct) => ct.id));

  const pickerOptions = (searchTypesQuery.data?.results ?? [])
    .filter((ct) => !linkedIds.has(ct.id))
    .map((ct) => ({ value: String(ct.id), label: ct.label }));

  const addMutation = useMutation({
    mutationFn: (charTypeId: number) => addCategoryCharType(categoryId, charTypeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: charTypeKeys.all });
      qc.invalidateQueries({ queryKey: categoryKeys.all });
      setPickerSearch('');
    },
  });

  const assignMutation = useMutation({
    mutationFn: (ids: number[]) => assignProducts(categoryId, ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: productKeys.all });
      qc.invalidateQueries({ queryKey: categoryKeys.all });
      setSelected(new Set());
    },
  });

  const totalPages = Math.ceil((unassignedQuery.data?.count ?? 0) / PAGE_SIZE);

  return (
    <Stack>
      <Title order={2}>{categoryQuery.data?.name ?? '…'}</Title>

      <Card withBorder padding="md">
        <Stack>
          <Group justify="space-between">
            <Text fw={600}>Типы характеристик</Text>
            <Text component={Link} to="/products/characteristics" size="sm">
              Создать новый тип →
            </Text>
          </Group>

          <MultiSelect
            placeholder="Добавить тип..."
            searchable
            data={pickerOptions}
            searchValue={pickerSearch}
            onSearchChange={setPickerSearch}
            value={[]}
            onChange={(vals) => {
              if (vals.length > 0) addMutation.mutate(Number(vals[0]));
            }}
            filter={({ options }) => options}
            nothingFoundMessage={debouncedSearch ? 'Ничего не найдено' : 'Начните вводить название'}
          />

          {linkedTypesQuery.isLoading ? (
            <Loader size="sm" />
          ) : (
            <Table>
              <Table.Tbody>
                {(linkedTypesQuery.data?.results ?? []).map((ct) => (
                  <CharTypeRow
                    key={ct.id}
                    charType={ct}
                    categoryId={categoryId}
                    onRemoved={() => {
                      qc.invalidateQueries({ queryKey: charTypeKeys.all });
                      qc.invalidateQueries({ queryKey: categoryKeys.all });
                    }}
                  />
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Card>

      <Card withBorder padding="md">
        <Stack>
          <Text fw={600}>Назначить продукты</Text>
          <TextInput
            placeholder="Поиск продуктов..."
            value={productSearch}
            onChange={(e) => setProductSearch(e.currentTarget.value)}
          />

          {unassignedQuery.isLoading ? (
            <Loader size="sm" />
          ) : (
            <Table>
              <Table.Tbody>
                {(unassignedQuery.data?.results ?? []).map((p) => (
                  <Table.Tr key={p.id}>
                    <Table.Td>
                      <Checkbox
                        aria-label={p.name}
                        checked={selected.has(p.id)}
                        onChange={(e) => {
                          const next = new Set(selected);
                          if (e.currentTarget.checked) next.add(p.id);
                          else next.delete(p.id);
                          setSelected(next);
                        }}
                      />
                    </Table.Td>
                    <Table.Td>{p.sku}</Table.Td>
                    <Table.Td>{p.name}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}

          {totalPages > 1 && (
            <Pagination total={totalPages} value={productPage} onChange={setProductPage} />
          )}

          <Group justify="flex-end">
            <Button
              disabled={selected.size === 0}
              loading={assignMutation.isPending}
              onClick={() => assignMutation.mutate([...selected])}
            >
              Назначить ({selected.size})
            </Button>
          </Group>
        </Stack>
      </Card>
    </Stack>
  );
}

interface CharTypeRowProps {
  charType: CharacteristicType;
  categoryId: number;
  onRemoved: () => void;
}

function CharTypeRow({ charType, categoryId, onRemoved }: CharTypeRowProps) {
  const [opened, { open, close }] = useDisclosure(false);
  const [usageCount, setUsageCount] = useState<number | null>(null);

  const removeMutation = useMutation({
    mutationFn: () => removeCategoryCharType(categoryId, charType.id),
    onSuccess: () => {
      close();
      onRemoved();
    },
  });

  async function handleOpenPopover() {
    const { count } = await getCategoryCharTypeUsage(categoryId, charType.id);
    setUsageCount(count);
    open();
  }

  return (
    <Table.Tr>
      <Table.Td>{charType.label}</Table.Td>
      <Table.Td>{charType.unit}</Table.Td>
      <Table.Td>
        <Popover opened={opened} onClose={close}>
          <Popover.Target>
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label="Удалить тип"
              onClick={handleOpenPopover}
            >
              <IconTrash size={14} />
            </ActionIcon>
          </Popover.Target>
          <Popover.Dropdown>
            <Stack gap="xs">
              <Text size="sm">Используется в {usageCount} продуктах. Удалить?</Text>
              <Group gap="xs">
                <Button
                  size="xs"
                  color="red"
                  loading={removeMutation.isPending}
                  onClick={() => removeMutation.mutate()}
                >
                  Удалить
                </Button>
                <Button size="xs" variant="default" onClick={close}>
                  Отмена
                </Button>
              </Group>
            </Stack>
          </Popover.Dropdown>
        </Popover>
      </Table.Td>
    </Table.Tr>
  );
}
