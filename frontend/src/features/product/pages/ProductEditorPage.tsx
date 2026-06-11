import { Button, Group, Loader, Stack, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconArrowLeft } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AxiosError } from 'axios';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { createProduct, getProduct, updateProduct } from '../api';
import { ProductForm } from '../components/ProductForm';
import { productKeys } from '../queryKeys';
import type { ProductWritePayload } from '../types';

function parseCharacteristicErrors(err: unknown): Record<string, string> | undefined {
  if (!(err instanceof AxiosError)) return undefined;
  const data = err.response?.data;
  if (!data || typeof data !== 'object') return undefined;
  const chars = (data as { characteristics?: unknown }).characteristics;
  if (!Array.isArray(chars)) return undefined;
  const out: Record<string, string> = {};
  for (const entry of chars) {
    if (typeof entry !== 'string') continue;
    const [key, ...rest] = entry.split(':');
    if (key && rest.length > 0) {
      out[`characteristics.${key.trim()}`] = rest.join(':').trim();
    }
  }
  return out;
}

export function ProductEditorPage() {
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);
  const productId = id ? Number(id) : undefined;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string> | undefined>();

  const { data: product, isLoading } = useQuery({
    queryKey: productId !== undefined ? productKeys.detail(productId) : ['product', 'new'],
    queryFn: () => getProduct(productId!),
    enabled: productId !== undefined && Number.isFinite(productId),
  });

  const mutation = useMutation({
    mutationFn: (payload: ProductWritePayload) =>
      isEdit ? updateProduct(productId!, payload) : createProduct(payload),
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: productKeys.all });
      notifications.show({ message: isEdit ? 'Сохранено' : 'Создано', color: 'green' });
      navigate(`/products/${saved.id}`);
    },
    onError: (err) => {
      const parsed = parseCharacteristicErrors(err);
      if (parsed) setFieldErrors(parsed);
      notifications.show({ message: 'Ошибка сохранения', color: 'red' });
    },
  });

  if (isEdit && isLoading) return <Loader />;

  return (
    <Stack>
      <Group>
        <Button
          variant="subtle"
          leftSection={<IconArrowLeft size={16} />}
          component={Link}
          to={isEdit && productId !== undefined ? `/products/${productId}` : '/products'}
        >
          Назад
        </Button>
        <Title order={2}>{isEdit ? 'Редактирование товара' : 'Новый товар'}</Title>
      </Group>
      <ProductForm
        initial={product}
        submitting={mutation.isPending}
        fieldErrors={fieldErrors}
        onSubmit={(payload) => {
          setFieldErrors(undefined);
          mutation.mutate(payload);
        }}
      />
    </Stack>
  );
}
