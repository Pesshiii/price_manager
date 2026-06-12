import { useMemo } from 'react';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { Stack, Text } from '@mantine/core';
import { usePreviewColumns } from '../hooks/usePreviewColumns';
import type { Instructions, Step, TransformSpec } from '../types';
import { AddStepMenu } from './AddStepMenu';
import { StepItem } from './StepItem';

interface Props {
  steps: Step[];
  transforms: TransformSpec[];
  selectedIndex: number | null;
  errorIndex: number | null;
  /** Full pipeline state — used to compute per-step "columns before this step". */
  instructions: Instructions;
  sessionId: string | null;
  /** Receives focus state to gate per-step column previews to expanded steps. */
  onSelect: (index: number) => void;
  onAdd: (spec: TransformSpec) => void;
  onRemove: (index: number) => void;
  onReorder: (next: Step[]) => void;
  onChangeArgs: (index: number, args: Record<string, unknown>) => void;
  onCommit: () => void;
}

function stepKey(step: Step, index: number): string {
  return `${index}:${step.func}`;
}

interface RowProps {
  id: string;
  index: number;
  step: Step;
  spec: TransformSpec | undefined;
  selected: boolean;
  hasError: boolean;
  instructions: Instructions;
  sessionId: string | null;
  enableColumnFetch: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onChangeArgs: (args: Record<string, unknown>) => void;
  onCommit: () => void;
}

function StepRow(props: RowProps) {
  const { columns } = usePreviewColumns({
    instructions: props.instructions,
    sessionId: props.sessionId,
    upTo: props.index,
    enabled: props.enableColumnFetch,
  });
  return (
    <StepItem
      id={props.id}
      index={props.index}
      step={props.step}
      spec={props.spec}
      selected={props.selected}
      hasError={props.hasError}
      availableColumns={columns}
      onSelect={props.onSelect}
      onRemove={props.onRemove}
      onChangeArgs={props.onChangeArgs}
      onCommit={props.onCommit}
    />
  );
}

export function StepList({
  steps,
  transforms,
  selectedIndex,
  errorIndex,
  instructions,
  sessionId,
  onSelect,
  onAdd,
  onRemove,
  onReorder,
  onChangeArgs,
  onCommit,
}: Props) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const ids = useMemo(() => steps.map(stepKey), [steps]);
  const specByName = useMemo(
    () => new Map(transforms.map((t) => [t.name, t])),
    [transforms],
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from === -1 || to === -1) return;
    onReorder(arrayMove(steps, from, to));
  }

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600} c="dimmed">
        Шаги преобразования
      </Text>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          <Stack gap="xs">
            {steps.length === 0 && (
              <Text size="xs" c="dimmed">
                Шагов нет. Добавьте трансформацию.
              </Text>
            )}
            {steps.map((step, idx) => (
              <StepRow
                key={ids[idx]}
                id={ids[idx]}
                index={idx}
                step={step}
                spec={specByName.get(step.func)}
                selected={selectedIndex === idx}
                hasError={errorIndex === idx}
                instructions={instructions}
                sessionId={sessionId}
                enableColumnFetch={selectedIndex === idx}
                onSelect={() => onSelect(idx)}
                onRemove={() => onRemove(idx)}
                onChangeArgs={(args) => onChangeArgs(idx, args)}
                onCommit={onCommit}
              />
            ))}
          </Stack>
        </SortableContext>
      </DndContext>
      <AddStepMenu transforms={transforms} onAdd={onAdd} />
    </Stack>
  );
}
