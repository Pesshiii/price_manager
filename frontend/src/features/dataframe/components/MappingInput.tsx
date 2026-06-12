import { useMemo } from 'react';
import { ActionIcon, Button, Group, Select, Stack, Text, TextInput } from '@mantine/core';
import { IconPlus, IconX, IconArrowRight } from '@tabler/icons-react';

interface Pair {
  key: string;
  value: string;
}

interface Props {
  /** Current value: either an object or a legacy "key=value" multi-line string. */
  value: unknown;
  onChange: (next: Record<string, string>) => void;
  onCommit?: () => void;
  /** When true, the "key" field is a Select from `keyOptions` (column names). */
  keyAsColumn: boolean;
  keyOptions?: string[];
  keyLabel?: string;
  valueLabel?: string;
  label?: string;
  description?: string;
  required?: boolean;
}

function parseValue(value: unknown): Pair[] {
  if (Array.isArray(value)) {
    return value
      .filter((p) => typeof p === 'object' && p !== null)
      .map((p) => ({ key: String((p as Pair).key ?? ''), value: String((p as Pair).value ?? '') }));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).map(([k, v]) => ({
      key: String(k),
      value: String(v ?? ''),
    }));
  }
  if (typeof value === 'string') {
    return value
      .split(/\r?\n/)
      .map((line) => {
        const idx = line.indexOf('=');
        if (idx < 0) return null;
        return { key: line.slice(0, idx).trim(), value: line.slice(idx + 1).trim() };
      })
      .filter((p): p is Pair => p !== null && p.key !== '');
  }
  return [];
}

function pairsToRecord(pairs: Pair[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of pairs) {
    if (p.key) out[p.key] = p.value;
  }
  return out;
}

export function MappingInput({
  value,
  onChange,
  onCommit,
  keyAsColumn,
  keyOptions = [],
  keyLabel,
  valueLabel,
  label,
  description,
  required,
}: Props) {
  const pairs = useMemo(() => parseValue(value), [value]);
  // Always render at least one empty row so the UI shows the shape.
  const rows = pairs.length > 0 ? pairs : [{ key: '', value: '' }];

  function update(next: Pair[]) {
    onChange(pairsToRecord(next));
  }

  function addRow() {
    update([...rows.filter((r) => r.key || r.value), { key: '', value: '' }]);
  }

  function removeRow(idx: number) {
    update(rows.filter((_, i) => i !== idx));
    onCommit?.();
  }

  // Reserve already-used keys when offering column options to avoid duplicates.
  const usedKeys = new Set(rows.map((r) => r.key).filter(Boolean));

  return (
    <Stack gap={4}>
      {label && (
        <Text size="sm" fw={500}>
          {label}
          {required && <span style={{ color: 'var(--mantine-color-red-6)' }}> *</span>}
        </Text>
      )}
      {description && (
        <Text size="xs" c="dimmed">
          {description}
        </Text>
      )}
      <Stack gap="xs">
        {rows.map((row, idx) => {
          const keyData = keyAsColumn
            ? keyOptions
                .filter((o) => o === row.key || !usedKeys.has(o))
                .map((c) => ({ value: c, label: c }))
            : [];
          return (
            <Group key={idx} gap="xs" wrap="nowrap" align="flex-end">
              {keyAsColumn ? (
                <Select
                  flex={1}
                  placeholder={keyLabel ?? 'Колонка'}
                  data={keyData}
                  value={row.key || null}
                  onChange={(v) => {
                    const next = [...rows];
                    next[idx] = { ...row, key: v ?? '' };
                    update(next);
                  }}
                  onBlur={onCommit}
                  searchable
                  clearable
                  aria-label={keyLabel ?? 'Колонка'}
                />
              ) : (
                <TextInput
                  flex={1}
                  placeholder={keyLabel ?? 'Старое'}
                  value={row.key}
                  onChange={(e) => {
                    const next = [...rows];
                    next[idx] = { ...row, key: e.currentTarget.value };
                    update(next);
                  }}
                  onBlur={onCommit}
                  aria-label={keyLabel ?? 'Старое'}
                />
              )}
              <IconArrowRight size={16} style={{ flexShrink: 0, opacity: 0.5 }} />
              <TextInput
                flex={1}
                placeholder={valueLabel ?? 'Новое'}
                value={row.value}
                onChange={(e) => {
                  const next = [...rows];
                  next[idx] = { ...row, value: e.currentTarget.value };
                  update(next);
                }}
                onBlur={onCommit}
                aria-label={valueLabel ?? 'Новое'}
              />
              <ActionIcon
                variant="subtle"
                color="red"
                onClick={() => removeRow(idx)}
                aria-label="Удалить строку"
              >
                <IconX size={14} />
              </ActionIcon>
            </Group>
          );
        })}
      </Stack>
      <Group justify="flex-start">
        <Button
          size="xs"
          variant="light"
          leftSection={<IconPlus size={12} />}
          onClick={addRow}
        >
          Добавить
        </Button>
      </Group>
    </Stack>
  );
}
