import { Badge, Card, Group, ScrollArea, Stack, Table, Text } from '@mantine/core';
import type { ImportPreviewResult, ImportRowErrors } from '../../types';

export interface ImportPreviewResultsProps {
  result: ImportPreviewResult;
}

/**
 * Нормализует разнородные shape'ы ошибок строки в плоский список сообщений.
 * Бэкенд может вернуть массив строк, объект {field: [msg]} или строку.
 */
export function normalizeRowErrors(errors: ImportRowErrors): string[] {
  if (errors == null) return [];
  if (typeof errors === 'string') return [errors];
  if (Array.isArray(errors)) {
    return errors.filter((e): e is string => typeof e === 'string');
  }
  if (typeof errors === 'object') {
    const out: string[] = [];
    for (const [field, value] of Object.entries(errors)) {
      const messages = Array.isArray(value) ? value : [value];
      for (const msg of messages) {
        if (typeof msg !== 'string') continue;
        out.push(field === 'non_field_errors' ? msg : `${field}: ${msg}`);
      }
    }
    return out;
  }
  return [];
}

export function ImportPreviewResults({ result }: ImportPreviewResultsProps) {
  return (
    <Stack>
      <Group>
        <Badge color="green" variant="light">
          Валидных: {result.valid}
        </Badge>
        <Badge color="red" variant="light">
          С ошибками: {result.invalid}
        </Badge>
        <Text c="dimmed" size="sm">
          Показано {result.returned} из {result.total}
        </Text>
      </Group>
      <Card withBorder padding={0}>
        <ScrollArea h={400}>
          <Table stickyHeader>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>#</Table.Th>
                <Table.Th>Данные</Table.Th>
                <Table.Th>Ошибки</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {result.rows.map((row) => {
                const messages = normalizeRowErrors(row.errors);
                return (
                  <Table.Tr key={row.index}>
                    <Table.Td>{row.index}</Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {JSON.stringify(row.payload)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {messages.length === 0 ? (
                        <Badge size="xs" color="green">
                          OK
                        </Badge>
                      ) : (
                        <Stack gap={2}>
                          {messages.map((err, i) => (
                            <Text key={i} c="red" size="xs">
                              {err}
                            </Text>
                          ))}
                        </Stack>
                      )}
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Card>
    </Stack>
  );
}
