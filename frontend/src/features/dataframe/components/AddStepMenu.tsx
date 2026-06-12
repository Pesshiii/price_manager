import { Button, Menu } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import type { TransformSpec } from '../types';

interface Props {
  transforms: TransformSpec[];
  onAdd: (spec: TransformSpec) => void;
}

export function AddStepMenu({ transforms, onAdd }: Props) {
  return (
    <Menu position="bottom-start" withinPortal>
      <Menu.Target>
        <Button
          variant="light"
          size="xs"
          leftSection={<IconPlus size={14} />}
          aria-label="Добавить шаг"
        >
          Добавить шаг
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        {transforms.length === 0 && <Menu.Item disabled>Нет доступных трансформаций</Menu.Item>}
        {transforms.map((t) => (
          <Menu.Item key={t.name} onClick={() => onAdd(t)}>
            {t.label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
