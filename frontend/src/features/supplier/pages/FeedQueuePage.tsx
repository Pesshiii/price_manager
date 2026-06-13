import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  bulkCreateProducts,
  createProductFromEntry,
  getFeed,
  getFeedMapping,
  getSupplier,
  ignoreEntry,
  listQueueEntries,
  resolveEntry,
  searchProductsForQueue,
} from '../api';
import { supplierKeys } from '../queryKeys';
import type { BulkCreateProductsResult, SupplierFeedEntry } from '../types';

const DEBOUNCE_MS = 300;

export function FeedQueuePage() {
  const { id, feedId } = useParams<{ id: string; feedId: string }>();
  const supplierId = Number(id);
  const fId = Number(feedId);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const [page] = useState(1);
  const [localEntries, setLocalEntries] = useState<SupplierFeedEntry[] | null>(null);
  const initialised = useRef(false);

  // search modal state
  const [modalEntryId, setModalEntryId] = useState<number | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');

  // inline create-product form state
  const [createEntryId, setCreateEntryId] = useState<number | null>(null);
  const [createSku, setCreateSku] = useState('');
  const [createName, setCreateName] = useState('');

  // bulk-create dialog state
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [bulkNameColumn, setBulkNameColumn] = useState<string | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkCreateProductsResult | null>(null);

  const supplierQuery = useQuery({
    queryKey: supplierKeys.supplier(supplierId),
    queryFn: () => getSupplier(supplierId),
  });

  const feedQuery = useQuery({
    queryKey: supplierKeys.feed(fId),
    queryFn: () => getFeed(fId),
  });

  const mappingQuery = useQuery({
    queryKey: supplierKeys.mapping(feedQuery.data?.feed_mapping ?? 0),
    queryFn: () => getFeedMapping(feedQuery.data!.feed_mapping),
    enabled: feedQuery.data != null,
  });

  const queueQuery = useQuery({
    queryKey: supplierKeys.queue(fId, page),
    queryFn: () => listQueueEntries(fId, page),
  });

  useEffect(() => {
    if (queueQuery.data && !initialised.current) {
      initialised.current = true;
      setLocalEntries(queueQuery.data.results);
    }
  }, [queueQuery.data]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(searchInput), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const searchQuery = useQuery({
    queryKey: ['product-search', debouncedQ],
    queryFn: () => searchProductsForQueue(debouncedQ),
    enabled: debouncedQ.length > 0,
  });

  const entries = localEntries ?? [];

  useEffect(() => {
    if (localEntries !== null && localEntries.length === 0 && queueQuery.data?.next == null) {
      navigate(`/suppliers/${supplierId}/feeds/${fId}`);
    }
  }, [localEntries, queueQuery.data?.next, navigate, supplierId, fId]);

  function removeEntry(entryId: number) {
    setLocalEntries((prev) => (prev ?? []).filter((e) => e.id !== entryId));
  }

  const resolveMutation = useMutation({
    mutationFn: ({
      entryId,
      payload,
    }: {
      entryId: number;
      payload: { product_id: number } | { skipped: true };
    }) => resolveEntry(fId, entryId, payload),
    onSuccess: (_, { entryId }) => {
      removeEntry(entryId);
      qc.invalidateQueries({ queryKey: supplierKeys.queue(fId, page) });
    },
  });

  const createProductMutation = useMutation({
    mutationFn: ({ entryId, sku, name }: { entryId: number; sku: string; name: string }) =>
      createProductFromEntry(fId, entryId, { sku, name }),
    onSuccess: (_, { entryId }) => {
      removeEntry(entryId);
      setCreateEntryId(null);
      qc.invalidateQueries({ queryKey: supplierKeys.queue(fId, page) });
    },
  });

  const ignoreMutation = useMutation({
    mutationFn: ({ entryId }: { entryId: number }) => ignoreEntry(fId, entryId),
    onSuccess: (_, { entryId }) => {
      removeEntry(entryId);
      qc.invalidateQueries({ queryKey: supplierKeys.queue(fId, page) });
    },
  });

  const bulkCreateMutation = useMutation({
    mutationFn: (nameColumn: string) => bulkCreateProducts(fId, nameColumn),
    onSuccess: (result) => {
      setBulkResult(result);
    },
  });

  function openCreateForm(entry: SupplierFeedEntry) {
    setCreateEntryId(entry.id);
    setCreateSku(entry.supplier_sku);
    setCreateName('');
  }

  function closeCreateForm() {
    setCreateEntryId(null);
    setCreateSku('');
    setCreateName('');
  }

  function openModal(entryId: number) {
    setModalEntryId(entryId);
    setSearchInput('');
    setDebouncedQ('');
  }

  function closeModal() {
    setModalEntryId(null);
    setSearchInput('');
    setDebouncedQ('');
  }

  function handleSearchSelect(productId: number) {
    if (modalEntryId == null) return;
    resolveMutation.mutate(
      { entryId: modalEntryId, payload: { product_id: productId } },
      { onSuccess: () => closeModal() },
    );
  }

  function openBulkModal() {
    setBulkResult(null);
    setBulkNameColumn(mappingQuery.data?.name_column ?? null);
    setBulkModalOpen(true);
  }

  function closeBulkModal() {
    setBulkModalOpen(false);
    setBulkResult(null);
    setBulkNameColumn(null);

    if (bulkResult != null) {
      if (bulkResult.failed === 0) {
        navigate(`/suppliers/${supplierId}/feeds/${fId}`);
      } else {
        initialised.current = false;
        qc.invalidateQueries({ queryKey: supplierKeys.queue(fId, page) });
      }
    }
  }

  const mapping = mappingQuery.data;
  const columnOptions = mapping
    ? [mapping.name_column, ...mapping.variable_columns]
        .filter((v, i, arr) => v && arr.indexOf(v) === i)
        .map((c) => ({ value: c, label: c }))
    : [];

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <Anchor component={Link} to={`/suppliers/${supplierId}/feeds/${fId}`} size="sm" c="dimmed">
            ← Выгрузка
          </Anchor>
          {supplierQuery.data && <Title order={2}>{supplierQuery.data.name}</Title>}
        </Group>
        <Button
          variant="light"
          onClick={openBulkModal}
          disabled={entries.length === 0 || mappingQuery.isLoading || mappingQuery.isError}
        >
          Создать всё оставшееся
        </Button>
      </Group>

      <Stack gap="md">
        {entries.map((entry) => (
          <Card key={entry.id} withBorder padding="md">
            <Stack gap="sm">
              <Group>
                <Text fw={600}>{entry.supplier_sku}</Text>
                {entry.best_score != null ? (
                  <Badge size="sm" variant="light" color="blue">
                    {Math.round(entry.best_score * 100)}%
                  </Badge>
                ) : (
                  <Badge size="sm" variant="light" color="gray">
                    Нет совпадений
                  </Badge>
                )}
                {Object.entries(entry.data).map(([k, v]) => (
                  <Text key={k} size="sm" c="dimmed">
                    {String(v)}
                  </Text>
                ))}
              </Group>

              <Stack gap={4}>
                {entry.match_candidates.map((c) => (
                  <Group key={c.product_id} justify="space-between">
                    <Group gap="xs">
                      <Text size="sm" fw={500}>
                        {c.name}
                      </Text>
                      <Text size="sm" c="dimmed">
                        {c.sku}
                      </Text>
                      <Text size="sm" c="dimmed">
                        {c.category}
                      </Text>
                      <Badge size="sm" variant="light">
                        {Math.round(c.score * 100)}%
                      </Badge>
                    </Group>
                    <Button
                      size="xs"
                      loading={
                        resolveMutation.isPending &&
                        resolveMutation.variables?.entryId === entry.id
                      }
                      onClick={() =>
                        resolveMutation.mutate({
                          entryId: entry.id,
                          payload: { product_id: c.product_id },
                        })
                      }
                    >
                      Подтвердить
                    </Button>
                  </Group>
                ))}
              </Stack>

              {createEntryId === entry.id ? (
                <Stack gap="xs">
                  <TextInput
                    size="xs"
                    label="Артикул"
                    value={createSku}
                    onChange={(e) => setCreateSku(e.currentTarget.value)}
                  />
                  <TextInput
                    size="xs"
                    label="Название"
                    value={createName}
                    onChange={(e) => setCreateName(e.currentTarget.value)}
                    placeholder="Введите название товара"
                  />
                  <Group gap="xs">
                    <Button
                      size="xs"
                      loading={
                        createProductMutation.isPending &&
                        createProductMutation.variables?.entryId === entry.id
                      }
                      disabled={!createSku.trim() || !createName.trim()}
                      onClick={() =>
                        createProductMutation.mutate({
                          entryId: entry.id,
                          sku: createSku.trim(),
                          name: createName.trim(),
                        })
                      }
                    >
                      Создать
                    </Button>
                    <Button size="xs" variant="subtle" color="gray" onClick={closeCreateForm}>
                      Отмена
                    </Button>
                  </Group>
                </Stack>
              ) : (
                <Group gap="xs">
                  <Button size="xs" variant="subtle" onClick={() => openModal(entry.id)}>
                    Найти вручную
                  </Button>
                  <Button size="xs" variant="subtle" onClick={() => openCreateForm(entry)}>
                    Создать товар
                  </Button>
                  <Button
                    size="xs"
                    variant="subtle"
                    color="gray"
                    loading={
                      resolveMutation.isPending &&
                      resolveMutation.variables?.entryId === entry.id
                    }
                    onClick={() =>
                      resolveMutation.mutate({ entryId: entry.id, payload: { skipped: true } })
                    }
                  >
                    Пропустить
                  </Button>
                  <Button
                    size="xs"
                    variant="subtle"
                    color="red"
                    loading={
                      ignoreMutation.isPending &&
                      ignoreMutation.variables?.entryId === entry.id
                    }
                    onClick={() => ignoreMutation.mutate({ entryId: entry.id })}
                  >
                    Игнорировать
                  </Button>
                </Group>
              )}
            </Stack>
          </Card>
        ))}
      </Stack>

      {/* Search modal */}
      <Modal opened={modalEntryId != null} onClose={closeModal} title="Поиск товара">
        <Stack gap="sm">
          <TextInput
            placeholder="Введите название или артикул"
            value={searchInput}
            onChange={(e) => setSearchInput(e.currentTarget.value)}
          />
          {searchQuery.isFetching && <Loader size="sm" />}
          <Stack gap={4}>
            {(searchQuery.data?.results ?? []).map((p) => (
              <UnstyledButton
                key={p.id}
                onClick={() => handleSearchSelect(p.id)}
                style={{ padding: '6px 8px', borderRadius: 4 }}
              >
                <Group gap="xs">
                  <Text size="sm" fw={500}>
                    {p.name}
                  </Text>
                  <Text size="sm" c="dimmed">
                    {p.sku}
                  </Text>
                </Group>
              </UnstyledButton>
            ))}
          </Stack>
        </Stack>
      </Modal>

      {/* Bulk create modal */}
      <Modal
        opened={bulkModalOpen}
        onClose={closeBulkModal}
        title="Создать все оставшееся"
        closeOnClickOutside={!bulkCreateMutation.isPending}
        closeOnEscape={!bulkCreateMutation.isPending}
      >
        <Stack gap="md">
          {bulkResult == null ? (
            <>
              <Text size="sm" c="dimmed">
                Будет создан новый товар для каждой нерешённой записи очереди. Записи с
                конфликтующим артикулом или пустым именем будут пропущены.
              </Text>
              <Select
                label="Колонка для названия товара"
                placeholder="Выберите колонку"
                data={columnOptions}
                value={bulkNameColumn}
                onChange={setBulkNameColumn}
              />
              <Group justify="flex-end" gap="xs">
                <Button
                  variant="subtle"
                  color="gray"
                  onClick={closeBulkModal}
                  disabled={bulkCreateMutation.isPending}
                >
                  Отмена
                </Button>
                <Button
                  loading={bulkCreateMutation.isPending}
                  disabled={bulkNameColumn == null}
                  onClick={() => bulkCreateMutation.mutate(bulkNameColumn!)}
                >
                  Создать все
                </Button>
              </Group>
            </>
          ) : (
            <>
              <Group gap="xs">
                <Badge color="green" size="lg">
                  Создано: {bulkResult.created}
                </Badge>
                {bulkResult.failed > 0 && (
                  <Badge color="red" size="lg">
                    Ошибки: {bulkResult.failed}
                  </Badge>
                )}
              </Group>
              {bulkResult.errors.length > 0 && (
                <Stack gap={4}>
                  {bulkResult.errors.map((e) => (
                    <Text key={e.entry_id} size="sm" c="red">
                      #{e.entry_id}: {e.reason}
                    </Text>
                  ))}
                </Stack>
              )}
              <Group justify="flex-end">
                <Button onClick={closeBulkModal}>Закрыть</Button>
              </Group>
            </>
          )}
        </Stack>
      </Modal>
    </Stack>
  );
}
