import { ActionIcon, Button, Group, TextInput, Tooltip } from '@mantine/core';
import { IconArrowBackUp, IconArrowForwardUp, IconDeviceFloppy } from '@tabler/icons-react';

interface Props {
  name: string;
  onChangeName: (next: string) => void;
  onCommitName: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onSave: () => void;
  saving: boolean;
  dirty: boolean;
  canSave: boolean;
}

export function UndoRedoToolbar({
  name,
  onChangeName,
  onCommitName,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onSave,
  saving,
  dirty,
  canSave,
}: Props) {
  return (
    <Group justify="space-between" wrap="nowrap">
      <TextInput
        flex={1}
        placeholder="Название пайплайна"
        value={name}
        onChange={(e) => onChangeName(e.currentTarget.value)}
        onBlur={onCommitName}
        aria-label="Название пайплайна"
      />
      <Group gap="xs">
        <Tooltip label="Отменить (Undo)">
          <ActionIcon
            variant="light"
            onClick={onUndo}
            disabled={!canUndo}
            aria-label="Отменить"
          >
            <IconArrowBackUp size={16} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label="Вернуть (Redo)">
          <ActionIcon
            variant="light"
            onClick={onRedo}
            disabled={!canRedo}
            aria-label="Вернуть"
          >
            <IconArrowForwardUp size={16} />
          </ActionIcon>
        </Tooltip>
        <Button
          leftSection={<IconDeviceFloppy size={16} />}
          onClick={onSave}
          loading={saving}
          disabled={!canSave || !dirty}
        >
          {dirty ? 'Сохранить' : 'Сохранено'}
        </Button>
      </Group>
    </Group>
  );
}
