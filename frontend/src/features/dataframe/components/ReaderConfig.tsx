import { Card, Group, Select, Stack, Text } from '@mantine/core';
import type { Instructions, ReaderSpec } from '../types';
import { ArgsForm } from './ArgsForm';

interface Props {
  readers: ReaderSpec[];
  reader: Instructions['reader'];
  selected: boolean;
  onSelect: () => void;
  onChangeFunc: (func: string) => void;
  onChangeArgs: (args: Record<string, unknown>) => void;
  onCommit: () => void;
}

export function ReaderConfig({
  readers,
  reader,
  selected,
  onSelect,
  onChangeFunc,
  onChangeArgs,
  onCommit,
}: Props) {
  const spec = readers.find((r) => r.name === reader.func);
  return (
    <Card
      withBorder
      padding="sm"
      onClick={onSelect}
      style={{
        cursor: 'pointer',
        borderColor: selected ? 'var(--mantine-color-blue-5)' : undefined,
      }}
      aria-label="Reader"
    >
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={600} c="dimmed">
            Источник (reader)
          </Text>
        </Group>
        <Select
          label="Функция чтения"
          placeholder="Выберите reader"
          data={readers.map((r) => ({
            value: r.name,
            label: `${r.label} (${r.extensions.join(', ')})`,
          }))}
          value={reader.func || null}
          onChange={(v) => onChangeFunc(v ?? '')}
          required
        />
        {spec && (
          <ArgsForm
            args={spec.args}
            values={reader.args}
            onChange={onChangeArgs}
            onCommit={onCommit}
          />
        )}
      </Stack>
    </Card>
  );
}
