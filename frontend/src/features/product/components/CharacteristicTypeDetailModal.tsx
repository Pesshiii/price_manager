import {
  Badge,
  Code,
  Group,
  Modal,
  Paper,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import type { CharacteristicType } from '../types';

interface Props {
  opened: boolean;
  onClose: () => void;
  type: CharacteristicType | null;
}

const VALUE_TYPE_LABELS: Record<CharacteristicType['value_type'], string> = {
  string: 'Строка',
  integer: 'Целое число',
  float: 'Число',
  boolean: 'Да/Нет',
  choice: 'Выбор из списка',
};

/**
 * Read-only inspector for a CharacteristicType. The list endpoint already
 * returns `categories_detail` (id + name + MPTT level) so this modal never
 * needs to fan out to `/categories/`.
 */
export function CharacteristicTypeDetailModal({ opened, onClose, type }: Props) {
  if (!type) return null;
  const cats = type.categories_detail ?? [];

  return (
    <Modal opened={opened} onClose={onClose} title={type.label || type.name} size="lg">
      <Stack gap="sm">
        <Group gap="lg">
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Ключ
            </Text>
            <Code>{type.name}</Code>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Тип значения
            </Text>
            <Text>{VALUE_TYPE_LABELS[type.value_type]}</Text>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Единица
            </Text>
            <Text>{type.unit || '—'}</Text>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Обязательная
            </Text>
            <Text>{type.required ? 'да' : 'нет'}</Text>
          </Stack>
        </Group>

        {type.value_type === 'choice' && type.options.length > 0 && (
          <Stack gap={4}>
            <Text size="xs" c="dimmed">
              Допустимые значения
            </Text>
            <Group gap={4}>
              {type.options.map((opt) => (
                <Badge key={opt} variant="light">
                  {opt}
                </Badge>
              ))}
            </Group>
          </Stack>
        )}

        <Stack gap={4}>
          <Title order={6}>Категории</Title>
          {cats.length === 0 ? (
            <Text c="dimmed" size="sm">
              Не привязана ни к одной категории.
            </Text>
          ) : (
            <Paper withBorder p="xs">
              <Stack gap={2}>
                {cats.map((c) => (
                  <Text key={c.id} size="sm">
                    {'— '.repeat(c.level) + c.name}
                  </Text>
                ))}
              </Stack>
            </Paper>
          )}
        </Stack>
      </Stack>
    </Modal>
  );
}
