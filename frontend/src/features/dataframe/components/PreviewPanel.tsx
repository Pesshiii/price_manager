import { Alert, Badge, Card, Group, Loader, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconUpload } from '@tabler/icons-react';
import type { InfiniteData } from '@tanstack/react-query';
import type { PreviewResult, PreviewSuccess, TransformSpec } from '../types';
import { isPreviewError } from '../types';
import { PreviewTable } from './PreviewTable';

interface Props {
  data: InfiniteData<PreviewResult> | undefined;
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  errorMessage?: string;
  hasSession: boolean;
  stepLabel: string;
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  fetchNextPage?: () => void;
  columnTransforms?: TransformSpec[];
  onColumnAction?: (column: string, transformName: string) => void;
}

export function PreviewPanel({
  data,
  isLoading,
  isFetching,
  isError,
  errorMessage,
  hasSession,
  stepLabel,
  hasNextPage = false,
  isFetchingNextPage = false,
  fetchNextPage,
  columnTransforms,
  onColumnAction,
}: Props) {
  if (!hasSession) {
    return (
      <Card withBorder padding="lg">
        <Stack align="center" gap="xs">
          <IconUpload size={28} />
          <Text c="dimmed">Загрузите файл, чтобы увидеть превью</Text>
        </Stack>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card withBorder padding="lg">
        <Group justify="center">
          <Loader size="sm" />
          <Text size="sm">Загружаем превью…</Text>
        </Group>
      </Card>
    );
  }

  if (isError) {
    return (
      <Alert color="red" icon={<IconAlertTriangle size={16} />}>
        {errorMessage || 'Не удалось получить превью'}
      </Alert>
    );
  }

  const firstPage = data?.pages[0];
  if (!firstPage) return null;

  if (isPreviewError(firstPage)) {
    return (
      <Alert color="red" icon={<IconAlertTriangle size={16} />} title="Ошибка в шаге">
        {firstPage.error.message}
      </Alert>
    );
  }

  const successPages = (data?.pages ?? []).filter(
    (p): p is PreviewSuccess => !isPreviewError(p),
  );
  const rows = successPages.flatMap((p) => p.rows);
  const columns = firstPage.columns;
  const totalRows = firstPage.total_rows;
  const loadedRows = rows.length;

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Group gap="xs">
          <Text size="sm" c="dimmed">
            После шага:
          </Text>
          <Badge variant="light">{stepLabel}</Badge>
        </Group>
        <Group gap="md">
          <Text size="xs" c="dimmed">
            Колонок: <b>{columns.length}</b>
          </Text>
          <Text size="xs" c="dimmed">
            Строк: <b>{totalRows}</b>{' '}
            {loadedRows < totalRows && <span>(загружено {loadedRows})</span>}
          </Text>
          {(isFetching || isFetchingNextPage) && <Loader size="xs" />}
        </Group>
      </Group>
      <PreviewTable
        columns={columns}
        rows={rows}
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        onEndReached={fetchNextPage}
        columnTransforms={columnTransforms}
        onColumnAction={onColumnAction}
      />
    </Stack>
  );
}
