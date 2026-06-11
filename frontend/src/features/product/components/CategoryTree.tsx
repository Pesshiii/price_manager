import { ActionIcon, Group, Stack, Text } from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { Link } from 'react-router-dom';
import type { Category } from '../types';

interface CategoryNode extends Category {
  children: CategoryNode[];
}

function buildTree(items: Category[]): CategoryNode[] {
  const map = new Map<number, CategoryNode>();
  items.forEach((c) => map.set(c.id, { ...c, children: [] }));
  const roots: CategoryNode[] = [];
  map.forEach((node) => {
    if (node.parent !== null && map.has(node.parent)) {
      map.get(node.parent)!.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

export interface CategoryTreeProps {
  categories: Category[];
  onAddChild: (parent: Category | null) => void;
  onDelete: (category: Category) => void;
  deletingId?: number;
}

export function CategoryTree({ categories, onAddChild, onDelete, deletingId }: CategoryTreeProps) {
  const tree = buildTree(categories);
  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Text fw={600}>Корни</Text>
        <ActionIcon variant="subtle" onClick={() => onAddChild(null)} aria-label="Добавить корневую">
          <IconPlus size={16} />
        </ActionIcon>
      </Group>
      {tree.map((node) => (
        <CategoryNodeRow
          key={node.id}
          node={node}
          depth={0}
          onAddChild={onAddChild}
          onDelete={onDelete}
          deletingId={deletingId}
        />
      ))}
    </Stack>
  );
}

interface RowProps {
  node: CategoryNode;
  depth: number;
  onAddChild: (parent: Category | null) => void;
  onDelete: (category: Category) => void;
  deletingId?: number;
}

function CategoryNodeRow({ node, depth, onAddChild, onDelete, deletingId }: RowProps) {
  return (
    <Stack gap={2} pl={depth * 16}>
      <Group justify="space-between" wrap="nowrap">
        <Text component={Link} to={`/products/categories/${node.id}`}>{node.name}</Text>
        <Group gap={4} wrap="nowrap">
          <ActionIcon
            variant="subtle"
            onClick={() => onAddChild(node)}
            aria-label="Добавить подкатегорию"
          >
            <IconPlus size={14} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            color="red"
            loading={deletingId === node.id}
            onClick={() => onDelete(node)}
            aria-label="Удалить категорию"
          >
            <IconTrash size={14} />
          </ActionIcon>
        </Group>
      </Group>
      {node.children.map((child) => (
        <CategoryNodeRow
          key={child.id}
          node={child}
          depth={depth + 1}
          onAddChild={onAddChild}
          onDelete={onDelete}
          deletingId={deletingId}
        />
      ))}
    </Stack>
  );
}
