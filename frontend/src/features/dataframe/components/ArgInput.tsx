import {
  Checkbox,
  MultiSelect,
  NumberInput,
  Select,
  TagsInput,
  TextInput,
  Textarea,
} from '@mantine/core';
import type { ArgSpec } from '../types';
import { MappingInput } from './MappingInput';

interface Props {
  spec: ArgSpec;
  value: unknown;
  onChange: (value: unknown) => void;
  onCommit?: () => void;
  availableColumns?: string[];
}

function asString(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value);
}

function asList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === 'string') {
    return value
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

export function ArgInput({ spec, value, onChange, onCommit, availableColumns }: Props) {
  const label = spec.label || spec.name;
  const required = spec.required;
  const description = spec.help_text || undefined;
  const columns = availableColumns ?? [];

  // Choices override any type-based rendering.
  if (spec.choices && spec.choices.length > 0) {
    return (
      <Select
        label={label}
        description={description}
        required={required}
        data={spec.choices.map((c) => ({ value: c, label: c }))}
        value={asString(value) || (asString(spec.default) ?? null)}
        onChange={(v) => onChange(v ?? '')}
        onBlur={onCommit}
        clearable={!required}
      />
    );
  }

  switch (spec.type) {
    case 'column': {
      const data = columns.map((c) => ({ value: c, label: c }));
      // Keep current value visible even if columns haven't loaded yet.
      const current = asString(value);
      if (current && !columns.includes(current)) {
        data.push({ value: current, label: `${current} (не найдено)` });
      }
      return (
        <Select
          label={label}
          description={description}
          required={required}
          placeholder={columns.length === 0 ? 'Колонки загружаются…' : 'Выберите колонку'}
          data={data}
          value={current || null}
          onChange={(v) => {
            onChange(v ?? '');
            onCommit?.();
          }}
          searchable
          clearable={!required}
        />
      );
    }
    case 'columns': {
      const data = columns.map((c) => ({ value: c, label: c }));
      const current = asList(value);
      // Pin any selected columns that are missing from the registry (renamed/dropped earlier).
      for (const c of current) {
        if (!columns.includes(c)) data.push({ value: c, label: `${c} (не найдено)` });
      }
      return (
        <MultiSelect
          label={label}
          description={description}
          required={required}
          placeholder={columns.length === 0 ? 'Колонки загружаются…' : 'Выберите колонки'}
          data={data}
          value={current}
          onChange={(v) => onChange(v)}
          onBlur={onCommit}
          searchable
          clearable
        />
      );
    }
    case 'column_mapping':
      return (
        <MappingInput
          label={label}
          description={description}
          required={required}
          value={value}
          onChange={(v) => onChange(v)}
          onCommit={onCommit}
          keyAsColumn
          keyOptions={columns}
          keyLabel="Старое имя"
          valueLabel="Новое имя"
        />
      );
    case 'value_mapping':
      return (
        <MappingInput
          label={label}
          description={description}
          required={required}
          value={value}
          onChange={(v) => onChange(v)}
          onCommit={onCommit}
          keyAsColumn={false}
          keyLabel="Старое значение"
          valueLabel="Новое значение"
        />
      );
    case 'bool':
      return (
        <Checkbox
          label={label}
          description={description}
          checked={!!value}
          onChange={(e) => {
            onChange(e.currentTarget.checked);
            onCommit?.();
          }}
        />
      );
    case 'int':
    case 'float':
      return (
        <NumberInput
          label={label}
          description={description}
          required={required}
          allowDecimal={spec.type === 'float'}
          value={value === '' || value === null || value === undefined ? '' : Number(value)}
          onChange={(v) => onChange(v)}
          onBlur={onCommit}
        />
      );
    case 'list[str]':
      return (
        <TagsInput
          label={label}
          description={description}
          required={required}
          placeholder="Введите и нажмите Enter"
          value={asList(value)}
          onChange={(v) => onChange(v)}
          onBlur={onCommit}
          clearable
        />
      );
    case 'dict[str,str]':
      return (
        <Textarea
          label={label}
          description={description || 'Каждая строка: ключ=значение'}
          required={required}
          autosize
          minRows={2}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.currentTarget.value)}
          onBlur={onCommit}
          placeholder="старое=новое"
        />
      );
    default:
      return (
        <TextInput
          label={label}
          description={description}
          required={required}
          value={asString(value)}
          onChange={(e) => onChange(e.currentTarget.value)}
          onBlur={onCommit}
        />
      );
  }
}
