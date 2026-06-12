import { ActionIcon, Badge, Card, Group, Stack, Text } from '@mantine/core';
import { IconGripVertical, IconTrash } from '@tabler/icons-react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { Step, TransformSpec } from '../types';
import { ArgsForm } from './ArgsForm';

interface Props {
  id: string;
  index: number;
  step: Step;
  spec: TransformSpec | undefined;
  selected: boolean;
  hasError: boolean;
  /** Column names available BEFORE this step is applied (for column selects). */
  availableColumns?: string[];
  onSelect: () => void;
  onRemove: () => void;
  onChangeArgs: (args: Record<string, unknown>) => void;
  onCommit: () => void;
}

export function StepItem({
  id,
  index,
  step,
  spec,
  selected,
  hasError,
  availableColumns,
  onSelect,
  onRemove,
  onChangeArgs,
  onCommit,
}: Props) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const borderColor = hasError
    ? 'var(--mantine-color-red-6)'
    : selected
    ? 'var(--mantine-color-blue-5)'
    : undefined;

  return (
    <Card
      ref={setNodeRef}
      withBorder
      padding="sm"
      style={{ ...style, borderColor, cursor: 'pointer' }}
      onClick={onSelect}
      data-testid={`step-${index}`}
      aria-label={`Шаг ${index + 1}: ${spec?.label ?? step.func}`}
    >
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <ActionIcon
              variant="subtle"
              size="sm"
              {...attributes}
              {...listeners}
              onClick={(e) => e.stopPropagation()}
              aria-label="Перетащить шаг"
            >
              <IconGripVertical size={16} />
            </ActionIcon>
            <Badge variant="light" size="sm">
              #{index + 1}
            </Badge>
            <Text size="sm" fw={500}>
              {spec?.label ?? step.func}
            </Text>
            {hasError && (
              <Badge color="red" size="xs" variant="light">
                ошибка
              </Badge>
            )}
          </Group>
          <ActionIcon
            variant="subtle"
            color="red"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            aria-label="Удалить шаг"
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
        {spec && (
          <ArgsForm
            args={spec.args}
            values={step.args}
            onChange={onChangeArgs}
            onCommit={onCommit}
            availableColumns={availableColumns}
          />
        )}
      </Stack>
    </Card>
  );
}
