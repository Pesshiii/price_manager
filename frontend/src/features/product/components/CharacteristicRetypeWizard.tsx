import {
  Alert,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';
import {
  useCharMutationInvalidation,
  useCharMutationJob,
  useRetypeCommit,
  useRetypePreview,
} from '../hooks/useCharMutations';
import {
  SMALL_INVALID_THRESHOLD,
  type CharacteristicType,
  type Fallback,
  type RetypePreviewResponse,
  type ValueType,
} from '../types';

interface Props {
  opened: boolean;
  onClose: () => void;
  /** The type whose `value_type` is being changed. */
  type: CharacteristicType;
  newValueType: ValueType;
  /** Notified on terminal status so the parent can chain (e.g. close edit modal). */
  onCompleted?: (success: boolean) => void;
}

type Phase = 'previewing' | 'configuring' | 'committing' | 'polling' | 'done';

const FALLBACK_OPTIONS: Array<{ value: Fallback; label: string }> = [
  { value: 'drop', label: 'Удалить ключ у товаров' },
  { value: 'null', label: 'Записать null' },
  { value: 'default', label: 'Подставить значение по умолчанию' },
];

export function CharacteristicRetypeWizard({
  opened,
  onClose,
  type,
  newValueType,
  onCompleted,
}: Props) {
  const previewMutation = useRetypePreview();
  const commitMutation = useRetypeCommit();
  const invalidate = useCharMutationInvalidation();

  const [phase, setPhase] = useState<Phase>('previewing');
  const [preview, setPreview] = useState<RetypePreviewResponse | null>(null);
  const [valueMap, setValueMap] = useState<Record<string, string>>({});
  const [fallback, setFallback] = useState<Fallback>('drop');
  const [defaultValue, setDefaultValue] = useState<string>('');
  const [jobId, setJobId] = useState<string | null>(null);

  const jobQuery = useCharMutationJob(jobId);
  const handledTerminalRef = useRef<string | null>(null);

  // ---- 1. Preview as soon as the modal opens. ----------------------------
  useEffect(() => {
    if (!opened) return;
    handledTerminalRef.current = null;
    setPhase('previewing');
    setPreview(null);
    setValueMap({});
    setFallback('drop');
    setDefaultValue('');
    setJobId(null);
    previewMutation.mutate(
      { id: type.id, new_value_type: newValueType },
      {
        onSuccess: (data) => {
          setPreview(data);
          if (data.invalid_count === 0) {
            // Nothing to resolve — go straight to commit.
            dispatchCommit(data, {}, 'drop', '');
          } else {
            setPhase('configuring');
          }
        },
        onError: () => {
          setPhase('configuring'); // surface error in UI
        },
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, type.id, newValueType]);

  // ---- 2. Submit handler — assembles the commit payload. ----------------
  function dispatchCommit(
    _pv: RetypePreviewResponse,
    map: Record<string, string>,
    fb: Fallback,
    def: string,
  ) {
    // Drop empties from value_map — they fall through to the fallback.
    const cleanMap: Record<string, unknown> = {};
    for (const [raw, replacement] of Object.entries(map)) {
      if (replacement.trim() !== '') cleanMap[raw] = replacement;
    }

    setPhase('committing');
    commitMutation.mutate(
      {
        id: type.id,
        body: {
          new_value_type: newValueType,
          fallback: fb,
          ...(fb === 'default' && def.trim() !== ''
            ? { default_value: def }
            : {}),
          ...(Object.keys(cleanMap).length > 0 ? { value_map: cleanMap } : {}),
        },
      },
      {
        onSuccess: (job) => {
          setJobId(job.id);
          setPhase('polling');
        },
        onError: () => {
          setPhase('configuring');
        },
      },
    );
  }

  // ---- 3. Watch the polled job for terminal status. ----------------------
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
        message: `Тип значения обновлён. Затронуто товаров: ${job.result?.updated ?? 0}.`,
        color: 'green',
      });
      setPhase('done');
      onCompleted?.(true);
    } else {
      notifications.show({
        message: `Ошибка смены типа: ${job.error}`,
        color: 'red',
      });
      setPhase('done');
      onCompleted?.(false);
    }
  }, [jobQuery.data, invalidate, onCompleted]);

  // ---- Render -----------------------------------------------------------

  const showPerValueTable =
    preview &&
    preview.unique_invalid.length > 0 &&
    preview.unique_invalid.length < SMALL_INVALID_THRESHOLD;

  function renderBody() {
    if (phase === 'previewing' || previewMutation.isPending) {
      return (
        <Group>
          <Loader size="sm" />
          <Text>Сканируем товары…</Text>
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
          {result && (
            <Code block>{JSON.stringify(result, null, 2)}</Code>
          )}
        </Stack>
      );
    }

    // phase === 'configuring' — user input
    if (!preview) {
      return (
        <Alert color="red" icon={<IconAlertTriangle size={16} />}>
          Не удалось получить превью изменений. Попробуйте позже.
        </Alert>
      );
    }

    return (
      <Stack>
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
          {preview.invalid_count} из {preview.total_with_key} товаров содержат
          значения, которые не приводятся к типу <b>{newValueType}</b>.
          {preview.truncated &&
            ' Уникальных битых значений больше 200 — отображены только первые.'}
        </Alert>

        {showPerValueTable && (
          <>
            <Text size="sm">
              Задайте замену для каждого уникального значения. Оставьте поле
              пустым, чтобы применить стратегию ниже.
            </Text>
            <Table withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Текущее значение</Table.Th>
                  <Table.Th>Количество товаров</Table.Th>
                  <Table.Th>Замена</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {preview.unique_invalid.map((u) => (
                  <Table.Tr key={u.value}>
                    <Table.Td>
                      <Code>{u.value}</Code>
                    </Table.Td>
                    <Table.Td>{u.count}</Table.Td>
                    <Table.Td>
                      <TextInput
                        value={valueMap[u.value] ?? ''}
                        onChange={(e) =>
                          setValueMap({
                            ...valueMap,
                            [u.value]: e.currentTarget.value,
                          })
                        }
                        placeholder="—"
                      />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </>
        )}

        <Select
          label="Что делать с непреобразуемыми значениями"
          data={FALLBACK_OPTIONS}
          value={fallback}
          onChange={(v) => setFallback((v ?? 'drop') as Fallback)}
          allowDeselect={false}
        />
        {fallback === 'default' && (
          <TextInput
            label="Значение по умолчанию"
            value={defaultValue}
            onChange={(e) => setDefaultValue(e.currentTarget.value)}
            placeholder={newValueType === 'integer' ? '0' : ''}
            required
          />
        )}
      </Stack>
    );
  }

  const submitDisabled =
    phase !== 'configuring' ||
    (fallback === 'default' && defaultValue.trim() === '');

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Сменить тип «${type.label || type.name}» → ${newValueType}`}
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
                onClick={() =>
                  preview && dispatchCommit(preview, valueMap, fallback, defaultValue)
                }
                disabled={submitDisabled}
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
