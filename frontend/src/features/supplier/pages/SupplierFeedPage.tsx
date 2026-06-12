import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { IconFileUpload, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  deleteFeed,
  deleteFile,
  getFeed,
  getFeedMapping,
  getSupplier,
  processFeed,
  uploadFile,
} from '../api';
import { supplierKeys } from '../queryKeys';
import type { SupplierFeedStatus, UploadedFile } from '../types';

const TERMINAL: SupplierFeedStatus[] = ['matched', 'partial', 'done', 'error'];

const STATUS_COLOR: Record<SupplierFeedStatus, string> = {
  draft: 'gray',
  processing: 'blue',
  matched: 'green',
  partial: 'yellow',
  done: 'teal',
  error: 'red',
};

interface Props {
  pollInterval?: number;
}

export function SupplierFeedPage({ pollInterval = 2000 }: Props) {
  const { id, feedId } = useParams<{ id: string; feedId: string }>();
  const supplierId = Number(id);
  const fId = Number(feedId);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);

  const feedQuery = useQuery({
    queryKey: supplierKeys.feed(fId),
    queryFn: () => getFeed(fId),
    refetchInterval: (query) =>
      TERMINAL.includes(query.state.data?.status as SupplierFeedStatus) ? false : pollInterval,
  });

  const supplierQuery = useQuery({
    queryKey: supplierKeys.supplier(supplierId),
    queryFn: () => getSupplier(supplierId),
  });

  const mappingQuery = useQuery({
    queryKey: supplierKeys.mapping(feedQuery.data?.feed_mapping ?? 0),
    queryFn: () => getFeedMapping(feedQuery.data!.feed_mapping),
    enabled: !!feedQuery.data,
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadFile(fId, file),
    onSuccess: (uploaded) => {
      setUploadedFiles((prev) => [...prev, uploaded]);
      qc.invalidateQueries({ queryKey: supplierKeys.feed(fId) });
    },
  });

  const deleteFileMutation = useMutation({
    mutationFn: (sessionId: string) => deleteFile(fId, sessionId),
    onSuccess: (_, sessionId) => {
      setUploadedFiles((prev) => prev.filter((f) => f.session_id !== sessionId));
      qc.invalidateQueries({ queryKey: supplierKeys.feed(fId) });
    },
  });

  const processMutation = useMutation({
    mutationFn: () => processFeed(fId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: supplierKeys.feed(fId) });
    },
  });

  const deleteFeedMutation = useMutation({
    mutationFn: () => deleteFeed(fId),
    onSuccess: () => navigate(`/suppliers/${supplierId}`),
  });

  const feed = feedQuery.data;
  const isDraft = feed?.status === 'draft';
  const isProcessing = feed?.status === 'processing';
  const isTerminal = feed ? TERMINAL.includes(feed.status) : false;
  const canProcess = isDraft && (feed?.session_ids.length ?? 0) > 0;

  return (
    <Stack>
      <Group>
        <Anchor component={Link} to={`/suppliers/${supplierId}`} size="sm" c="dimmed">
          ← Поставщики
        </Anchor>
      </Group>

      <Group>
        {supplierQuery.data && <Title order={2}>{supplierQuery.data.name}</Title>}
        {mappingQuery.data && <Text c="dimmed">{mappingQuery.data.name}</Text>}
        {feed && (
          <Group gap={8}>
            {isProcessing && <Loader size={16} />}
            <Badge color={STATUS_COLOR[feed.status] ?? 'gray'} variant="light">
              {isProcessing ? 'Обработка...' : feed.status}
            </Badge>
          </Group>
        )}
      </Group>

      {isDraft && (
        <Stack gap="xs">
          <Dropzone
            onDrop={(files) => {
              const file = files[0];
              if (file) uploadMutation.mutate(file);
            }}
            loading={uploadMutation.isPending}
            aria-label="Загрузить файлы"
          >
            <Group justify="center" gap="md" mih={80} style={{ pointerEvents: 'none' }}>
              <IconFileUpload size={28} />
              <Text size="sm" fw={500}>
                Перетащите файл или нажмите для выбора
              </Text>
            </Group>
          </Dropzone>

          {uploadedFiles.map((f) => (
            <Card key={f.session_id} withBorder padding="sm">
              <Group justify="space-between">
                <Stack gap={2}>
                  <Text size="sm" fw={500}>
                    {f.filename}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {(f.size / 1024).toFixed(1)} KB
                  </Text>
                </Stack>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label="Удалить файл"
                  loading={
                    deleteFileMutation.isPending && deleteFileMutation.variables === f.session_id
                  }
                  onClick={() => deleteFileMutation.mutate(f.session_id)}
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            </Card>
          ))}

          <Button
            disabled={!canProcess}
            loading={processMutation.isPending}
            onClick={() => processMutation.mutate()}
          >
            Обработать
          </Button>
        </Stack>
      )}

      {isProcessing && (
        <Group>
          <Loader size="sm" />
          <Text>Обрабатываем...</Text>
        </Group>
      )}

      {isTerminal && feed && (
        <Stack gap="sm">
          {(feed.status === 'matched' || feed.status === 'partial' || feed.status === 'done') && (
            <Group>
              <Text>
                Всего: <strong>{feed.total}</strong>
              </Text>
              <Text>
                Сопоставлено: <strong>{feed.matched}</strong>
              </Text>
              <Text>
                Пропущено: <strong>{feed.skipped}</strong>
              </Text>
            </Group>
          )}

          {feed.status === 'matched' && (
            <Text c="green" fw={500}>
              Все позиции сопоставлены
            </Text>
          )}

          {feed.status === 'partial' && (
            <Button
              component={Link}
              to={`/suppliers/${supplierId}/feeds/${fId}/queue`}
            >
              Разобрать очередь ({feed.queued})
            </Button>
          )}

          {feed.status === 'error' && (
            <Stack gap="xs">
              <Text c="red">{feed.error}</Text>
              <Button
                color="red"
                variant="light"
                loading={deleteFeedMutation.isPending}
                onClick={() => deleteFeedMutation.mutate()}
              >
                Удалить выгрузку
              </Button>
            </Stack>
          )}
        </Stack>
      )}
    </Stack>
  );
}
