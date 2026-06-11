import {
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { IconArrowLeft, IconEdit, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { deleteProduct, getProduct } from '../api';
import { useBrands } from '../hooks/useBrands';
import { useCategories } from '../hooks/useCategories';
import { useCharacteristicTypes } from '../hooks/useCharacteristicTypes';
import { productKeys } from '../queryKeys';

export function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const productId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: product, isLoading } = useQuery({
    queryKey: productKeys.detail(productId),
    queryFn: () => getProduct(productId),
    enabled: Number.isFinite(productId),
  });

  const { data: categories } = useCategories();
  const { data: brands } = useBrands();
  // Only fetch types that this product actually has values for — bounded by
  // the product's `characteristics` keys (a handful, not the whole catalog).
  const boundNames = product ? Object.keys(product.characteristics ?? {}) : [];
  const { data: charTypesPage } = useCharacteristicTypes(
    boundNames.length > 0 ? { name__in: boundNames, page_size: 500 } : {},
  );
  const charTypes = boundNames.length > 0 ? charTypesPage?.results ?? [] : [];

  const deleteMutation = useMutation({
    mutationFn: deleteProduct,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: productKeys.all });
      navigate('/products');
    },
  });

  if (isLoading) return <Loader />;
  if (!product) return <Text c="dimmed">Товар не найден</Text>;

  const categoryName = categories?.find((c) => c.id === product.category)?.name ?? '—';
  const brandName = brands?.find((b) => b.id === product.brand)?.name ?? '—';
  const charTypeMap = new Map((charTypes ?? []).map((t) => [t.name, t]));

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <Button
            variant="subtle"
            leftSection={<IconArrowLeft size={16} />}
            component={Link}
            to="/products"
          >
            К списку
          </Button>
          <Title order={2}>{product.name}</Title>
        </Group>
        <Group gap="xs">
          <Button
            variant="default"
            leftSection={<IconEdit size={16} />}
            component={Link}
            to={`/products/${product.id}/edit`}
          >
            Редактировать
          </Button>
          <Button
            color="red"
            variant="light"
            leftSection={<IconTrash size={16} />}
            loading={deleteMutation.isPending}
            onClick={() => {
              if (confirm(`Удалить «${product.name}»?`)) deleteMutation.mutate(product.id);
            }}
          >
            Удалить
          </Button>
        </Group>
      </Group>

      <Card withBorder padding="md">
        <Stack gap="xs">
          <Group>
            <Badge variant="light">SKU: {product.sku}</Badge>
            {product.status && <Badge>{product.status}</Badge>}
          </Group>
          <Text>
            <b>Категория:</b> {categoryName}
          </Text>
          <Text>
            <b>Бренд:</b> {brandName}
          </Text>
          {product.description && <Text>{product.description}</Text>}
        </Stack>
      </Card>

      {Object.keys(product.characteristics).length > 0 && (
        <Card withBorder padding={0}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Характеристика</Table.Th>
                <Table.Th>Значение</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(product.characteristics).map(([key, value]) => {
                const type = charTypeMap.get(key);
                return (
                  <Table.Tr key={key}>
                    <Table.Td>{type?.label ?? key}</Table.Td>
                    <Table.Td>
                      {String(value)}
                      {type?.unit ? ` ${type.unit}` : ''}
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </Stack>
  );
}
