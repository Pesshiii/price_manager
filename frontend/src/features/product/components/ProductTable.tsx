import { ActionIcon, Group, Table, Text } from '@mantine/core';
import { IconEdit, IconTrash } from '@tabler/icons-react';
import { Link } from 'react-router-dom';
import type { Brand, Category, Product } from '../types';

export interface ProductTableProps {
  products: Product[];
  categories: Category[];
  brands: Brand[];
  onDelete: (product: Product) => void;
  deletingId?: number;
  priceCols?: Array<{ slug: string; label: string }>;
}

function makeMap<T extends { id: number }>(items: T[]): Map<number, T> {
  return new Map(items.map((i) => [i.id, i]));
}

export function ProductTable({
  products,
  categories,
  brands,
  onDelete,
  deletingId,
  priceCols,
}: ProductTableProps) {
  const categoryMap = makeMap(categories);
  const brandMap = makeMap(brands);

  return (
    <Table striped highlightOnHover>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>SKU</Table.Th>
          <Table.Th>Название</Table.Th>
          <Table.Th>Категория</Table.Th>
          <Table.Th>Бренд</Table.Th>
          <Table.Th>Статус</Table.Th>
          <Table.Th>Обновлён</Table.Th>
          {priceCols?.map((c) => <Table.Th key={c.slug}>{c.label}</Table.Th>)}
          <Table.Th />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {products.map((p) => (
          <Table.Tr key={p.id}>
            <Table.Td>
              <Text component={Link} to={`/products/${p.id}`} fw={500}>
                {p.sku}
              </Text>
            </Table.Td>
            <Table.Td>{p.name}</Table.Td>
            <Table.Td>{p.category !== null ? categoryMap.get(p.category)?.name ?? '—' : '—'}</Table.Td>
            <Table.Td>{p.brand !== null ? brandMap.get(p.brand)?.name ?? '—' : '—'}</Table.Td>
            <Table.Td>{p.status || '—'}</Table.Td>
            <Table.Td>{new Date(p.updated_at).toLocaleString()}</Table.Td>
            {priceCols?.map((c) => (
              <Table.Td key={c.slug}>
                {p.prices?.[c.slug] != null
                  ? p.prices![c.slug]!.toLocaleString('ru-RU', { minimumFractionDigits: 2 })
                  : '—'}
              </Table.Td>
            ))}
            <Table.Td>
              <Group gap="xs" justify="flex-end">
                <ActionIcon
                  variant="subtle"
                  component={Link}
                  to={`/products/${p.id}/edit`}
                  aria-label="Редактировать"
                >
                  <IconEdit size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  loading={deletingId === p.id}
                  onClick={() => onDelete(p)}
                  aria-label="Удалить"
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
