import { Badge, Card, Group, ScrollArea, Stack, Table, Text } from '@mantine/core';
import type { CategoryImportPreviewResult, CategoryRowStatus } from '../../types';

const STATUS_COLOR: Record<CategoryRowStatus, string> = {
  new: 'blue',
  exists: 'gray',
  invalid: 'red',
};

const STATUS_LABEL: Record<CategoryRowStatus, string> = {
  new: 'Новая',
  exists: 'Существует',
  invalid: 'Ошибка',
};

export interface CategoryPreviewResultsProps {
  result: CategoryImportPreviewResult;
}

export function CategoryPreviewResults({ result }: CategoryPreviewResultsProps) {
  return (
    <Stack>
      <Group>
        <Badge color="blue" variant="light">
          Новых: {result.new}
        </Badge>
        <Badge color="gray" variant="light">
          Существует: {result.exists}
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
                <Table.Th>Путь</Table.Th>
                <Table.Th>Сегменты</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th>Ошибка</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {result.rows.map((row) => (
                <Table.Tr key={row.index}>
                  <Table.Td>{row.index}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{row.path}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {row.segments.join(' › ')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge size="xs" color={STATUS_COLOR[row.status]}>
                      {STATUS_LABEL[row.status]}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    {row.error && (
                      <Text size="xs" c="red">
                        {row.error}
                      </Text>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Card>
    </Stack>
  );
}
