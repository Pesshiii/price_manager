import {
  Alert,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';
import {
  useCharMutationInvalidation,
  useCharMutationJob,
  useRenameCommit,
  useRenamePreview,
} from '../hooks/useCharMutations';
import type {
  CharacteristicType,
  RenameConflict,
  RenamePreviewResponse,
} from '../types';

interface Props {
  opened: boolean;
  onClose: () => void;
  type: CharacteristicType;
  newName: string;
  onCompleted?: (success: boolean) => void;
}

type Phase = 'previewing' | 'configuring' | 'committing' | 'polling' | 'done';

const CONFLICT_OPTIONS: Array<{ value: RenameConflict; label: string }> = [
  { value: 'overwrite', label: 'Перезаписать' },
  { value: 'keep_existing', label: 'Оставить существующее' },
  { value: 'skip_row', label: 'Пропустить товар' },
];

export function CharacteristicRenameWizard({
  opened,
  onClose,
  type,
  newName,
  onCompleted,
}: Props) {
  const previewMutation = useRenamePreview();
  const commitMutation = useRenameCommit();
  const invalidate = useCharMutationInvalidation();

  const [phase, setPhase] = useState<Phase>('previewing');
  const [preview, setPreview] = useState<RenamePreviewResponse | null>(null);
  const [onConflict, setOnConflict] = useState<RenameConflict>('overwrite');
  const [jobId, setJobId] = useState<string | null>(null);

  const jobQuery = useCharMutationJob(jobId);
  const handledTerminalRef = useRef<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    handledTerminalRef.current = null;
    setPhase('previewing');
    setPreview(null);
    setOnConflict('overwrite');
    setJobId(null);
    previewMutation.mutate(
      { id: type.id, new_name: newName },
      {
        onSuccess: (data) => {
          setPreview(data);
          if (data.collision_count === 0) {
            // No conflicts → commit immediately (strategy is irrelevant).
            dispatchCommit('overwrite');
          } else {
            setPhase('configuring');
          }
        },
        onError: () => setPhase('configuring'),
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, type.id, newName]);

  function dispatchCommit(strategy: RenameConflict) {
    setPhase('committing');
    commitMutation.mutate(
      { id: type.id, body: { new_name: newName, on_conflict: strategy } },
      {
        onSuccess: (job) => {
          setJobId(job.id);
          setPhase('polling');
        },
        onError: () => setPhase('configuring'),
      },
    );
  }

  useEffect(() => {
    const job = jobQuery.data;
    if (!job) return;
    if (job.status !== 'success' && job.status !== 'error') return;
    const key = `${job.id}:${job.status}`;
    if (handledTerminalRef.current === key) return;
    handledTerminalRef.current = key;

    if (job.status === 'success') {
      invalidate(job);
      notifications.show({
        message: `Переименовано: ${job.result?.renamed ?? 0} товар(ов).`,
        color: 'green',
      });
      setPhase('done');
      onCompleted?.(true);
    } else {
      notifications.show({
        message: `Ошибка переименования: ${job.error}`,
        color: 'red',
      });
      setPhase('done');
      onCompleted?.(false);
    }
  }, [jobQuery.data, invalidate, onCompleted]);

  function renderBody() {
    if (phase === 'previewing' || previewMutation.isPending) {
      return (
        <Group>
          <Loader size="sm" />
          <Text>Проверяем коллизии…</Text>
        </Group>
      );
    }
    if (phase === 'polling' || phase === 'committing') {
      const stage = jobQuery.data?.stage || 'Запускаем задачу…';
      return (
        <Group>
          <Loader size="sm" />
          <Text>{stage}</Text>
        </Group>
      );
    }
    if (phase === 'done') {
      const result = jobQuery.data?.result;
      return (
        <Stack gap="xs">
          <Text c="green">Готово.</Text>
          {result && <Code block>{JSON.stringify(result, null, 2)}</Code>}
        </Stack>
      );
    }
    if (!preview) {
      return (
        <Alert color="red" icon={<IconAlertTriangle size={16} />}>
          Не удалось получить превью переименования.
        </Alert>
      );
    }

    return (
      <Stack>
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
          У {preview.collision_count} товар(ов) уже есть ключ <Code>{newName}</Code>.
          Выберите, что делать со старым значением.
        </Alert>

        <SegmentedControl
          fullWidth
          data={CONFLICT_OPTIONS}
          value={onConflict}
          onChange={(v) => setOnConflict(v as RenameConflict)}
        />

        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Артикул</Table.Th>
              <Table.Th>Product ID</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {preview.collisions.map((c) => (
              <Table.Tr key={c.product_id}>
                <Table.Td>
                  <Code>{c.sku}</Code>
                </Table.Td>
                <Table.Td>{c.product_id}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    );
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Переименовать ключ «${type.name}» → ${newName}`}
      size="xl"
      closeOnClickOutside={phase !== 'polling' && phase !== 'committing'}
    >
      <Stack>
        {renderBody()}
        <Group justify="flex-end">
          {phase === 'done' ? (
            <Button onClick={onClose}>Закрыть</Button>
          ) : (
            <>
              <Button
                variant="default"
                onClick={onClose}
                disabled={phase === 'committing'}
              >
                Отмена
              </Button>
              <Button
                onClick={() => dispatchCommit(onConflict)}
                disabled={phase !== 'configuring'}
                loading={commitMutation.isPending}
              >
                Применить
              </Button>
            </>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}
