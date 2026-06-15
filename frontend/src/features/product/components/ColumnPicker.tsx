import { ActionIcon, Checkbox, Popover, Stack, Text } from '@mantine/core';
import { IconColumns } from '@tabler/icons-react';
import type { PriceType } from '@/features/pricing/types';

interface ColumnPickerProps {
  priceTypes: PriceType[];
  selectedPriceTypes: string[];
  onToggle: (slug: string) => void;
}

export function ColumnPicker({ priceTypes, selectedPriceTypes, onToggle }: ColumnPickerProps) {
  return (
    <Popover width={220} position="bottom-end" withArrow shadow="md">
      <Popover.Target>
        <ActionIcon variant="default" size="lg" aria-label="Выбрать колонки">
          <IconColumns size={16} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <Text size="sm" fw={500}>Ценовые колонки</Text>
          {priceTypes.length === 0 && (
            <Text size="xs" c="dimmed">Типы цен не найдены</Text>
          )}
          {priceTypes.map((pt) => (
            <Checkbox
              key={pt.name}
              label={pt.label}
              checked={selectedPriceTypes.includes(pt.name)}
              onChange={() => onToggle(pt.name)}
            />
          ))}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
