import { Stack } from '@mantine/core';
import type { ArgSpec } from '../types';
import { ArgInput } from './ArgInput';

interface Props {
  args: ArgSpec[];
  values: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  onCommit?: () => void;
  availableColumns?: string[];
}

export function ArgsForm({ args, values, onChange, onCommit, availableColumns }: Props) {
  if (args.length === 0) {
    return null;
  }
  return (
    <Stack gap="xs">
      {args.map((spec) => (
        <ArgInput
          key={spec.name}
          spec={spec}
          value={values[spec.name]}
          onChange={(v) => onChange({ ...values, [spec.name]: v })}
          onCommit={onCommit}
          availableColumns={availableColumns}
        />
      ))}
    </Stack>
  );
}
