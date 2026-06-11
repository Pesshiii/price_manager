import { NumberInput, Select, Switch, TextInput } from '@mantine/core';
import type { CharacteristicType, CharacteristicValue } from '../types';

export interface CharacteristicFieldProps {
  type: CharacteristicType;
  value: CharacteristicValue | undefined;
  onChange: (value: CharacteristicValue | undefined) => void;
  error?: string;
}

export function CharacteristicField({ type, value, onChange, error }: CharacteristicFieldProps) {
  const label = type.unit ? `${type.label} (${type.unit})` : type.label;
  const required = type.required;

  switch (type.value_type) {
    case 'integer':
      return (
        <NumberInput
          label={label}
          required={required}
          error={error}
          value={typeof value === 'number' ? value : ''}
          onChange={(v) => onChange(v === '' ? undefined : Number(v))}
          allowDecimal={false}
        />
      );
    case 'float':
      return (
        <NumberInput
          label={label}
          required={required}
          error={error}
          value={typeof value === 'number' ? value : ''}
          onChange={(v) => onChange(v === '' ? undefined : Number(v))}
          decimalScale={4}
        />
      );
    case 'boolean':
      return (
        <Switch
          label={label}
          checked={value === true}
          onChange={(e) => onChange(e.currentTarget.checked)}
          error={error}
        />
      );
    case 'choice':
      return (
        <Select
          label={label}
          required={required}
          error={error}
          data={type.options}
          value={typeof value === 'string' ? value : null}
          onChange={(v) => onChange(v ?? undefined)}
          clearable={!required}
          searchable
        />
      );
    case 'string':
    default:
      return (
        <TextInput
          label={label}
          required={required}
          error={error}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.currentTarget.value || undefined)}
        />
      );
  }
}
