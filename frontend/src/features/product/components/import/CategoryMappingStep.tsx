import { Select, Stack, TextInput } from '@mantine/core';
import type { CategoryImportMapping } from '../../types';

export interface CategoryMappingStepProps {
  columns: string[];
  mapping: CategoryImportMapping;
  onChange: (m: CategoryImportMapping) => void;
}

export function CategoryMappingStep({ columns, mapping, onChange }: CategoryMappingStepProps) {
  const columnData = columns.map((c) => ({ value: c, label: c }));

  return (
    <Stack>
      <Select
        label="Колонка с путём категории"
        description="Колонка, содержащая иерархический путь категории"
        placeholder="Выберите колонку"
        data={columnData}
        value={mapping.path_column ?? null}
        onChange={(v) => onChange({ ...mapping, path_column: v ?? '' })}
        required
        searchable
      />
      <TextInput
        label="Разделитель"
        description="Символ (или строка), разделяющий уровни иерархии"
        placeholder=">"
        value={mapping.separator ?? ''}
        onChange={(e) =>
          onChange({ ...mapping, separator: e.currentTarget.value || undefined })
        }
      />
    </Stack>
  );
}
