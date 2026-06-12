import { Button, Card, Group, Loader, Modal, Stack, TextInput, Title } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { createCategory, deleteCategory } from '../api';
import { CategoryTree } from '../components/CategoryTree';
import { useCategories } from '../hooks/useCategories';
import { categoryKeys } from '../queryKeys';
import type { Category } from '../types';

export function CategoriesPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useCategories();
  const [opened, { open, close }] = useDisclosure(false);
  const [parent, setParent] = useState<Category | null>(null);
  const [name, setName] = useState('');

  const createMutation = useMutation({
    mutationFn: createCategory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: categoryKeys.all });
      close();
      setName('');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCategory,
    onSuccess: () => qc.invalidateQueries({ queryKey: categoryKeys.all }),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Категории</Title>
        <Button component={Link} to="/products/categories/import" variant="default">
          Импортировать
        </Button>
      </Group>
      {isLoading && <Loader />}
      {!isLoading && (
        <Card withBorder padding="md">
          <CategoryTree
            categories={data ?? []}
            deletingId={deleteMutation.variables}
            onAddChild={(p) => {
              setParent(p);
              setName('');
              open();
            }}
            onDelete={(c) => {
              if (confirm(`Удалить «${c.name}»?`)) deleteMutation.mutate(c.id);
            }}
          />
        </Card>
      )}
      <Modal
        opened={opened}
        onClose={close}
        title={parent ? `Подкатегория «${parent.name}»` : 'Новая корневая категория'}
      >
        <Stack>
          <TextInput
            label="Название"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              Отмена
            </Button>
            <Button
              loading={createMutation.isPending}
              disabled={!name.trim()}
              onClick={() => createMutation.mutate({ name: name.trim(), parent: parent?.id ?? null })}
            >
              Создать
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
