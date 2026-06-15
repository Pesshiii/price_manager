import {
  Button,
  Card,
  Grid,
  Group,
  Loader,
  Pagination,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { IconDatabaseImport, IconPlus, IconSettings } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { deleteProduct } from '../api';
import { ColumnPicker } from '../components/ColumnPicker';
import { ProductFiltersSidebar } from '../components/ProductFiltersSidebar';
import { ProductTable } from '../components/ProductTable';
import { useBrands } from '../hooks/useBrands';
import { useCategories } from '../hooks/useCategories';
import { useColumnPicker } from '../hooks/useColumnPicker';
import { useProductFiltersFromUrl } from '../hooks/useProductFiltersFromUrl';
import { useProductList } from '../hooks/useProductList';
import { usePriceTypes } from '../hooks/usePriceTypes';
import { productKeys } from '../queryKeys';

export function ProductListPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { filters, patchFilters, toggleCharValue, resetFilters } = useProductFiltersFromUrl();
  const { selectedPriceTypes, togglePriceType } = useColumnPicker();
  const { data: priceTypes = [] } = usePriceTypes();
  const priceCols = priceTypes
    .filter((pt) => selectedPriceTypes.includes(pt.name))
    .map((pt) => ({ slug: pt.name, label: pt.label }));
  const { data, isLoading } = useProductList({ ...filters, price_types: selectedPriceTypes });
  const { data: categories } = useCategories();
  const { data: brands } = useBrands();

  const deleteMutation = useMutation({
    mutationFn: deleteProduct,
    onSuccess: () => qc.invalidateQueries({ queryKey: productKeys.all }),
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.count / filters.pageSize)) : 1;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Каталог товаров</Title>
        <Group gap="xs">
          <Button
            variant="default"
            leftSection={<IconSettings size={16} />}
            component={Link}
            to="/products/categories"
          >
            Справочники
          </Button>
          <Button
            variant="default"
            leftSection={<IconDatabaseImport size={16} />}
            component={Link}
            to="/products/import"
          >
            Импорт
          </Button>
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => navigate('/products/new')}
          >
            Новый товар
          </Button>
        </Group>
      </Group>

      <Grid>
        <Grid.Col span={{ base: 12, md: 3 }}>
          <Card withBorder padding="md">
            <ProductFiltersSidebar
              filters={filters}
              patchFilters={patchFilters}
              toggleCharValue={toggleCharValue}
              resetFilters={resetFilters}
              priceTypes={priceTypes}
            />
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 9 }}>
          <Stack>
            <Group justify="flex-end" mb="xs">
              <ColumnPicker
                priceTypes={priceTypes}
                selectedPriceTypes={selectedPriceTypes}
                onToggle={togglePriceType}
              />
            </Group>
            {isLoading && <Loader />}
            {!isLoading && (data?.results.length ?? 0) === 0 && (
              <Card withBorder padding="lg">
                <Stack align="center" gap="xs">
                  <Text c="dimmed">Товары не найдены</Text>
                </Stack>
              </Card>
            )}
            {!isLoading && (data?.results.length ?? 0) > 0 && (
              <Card withBorder padding={0}>
                <ProductTable
                  products={data!.results}
                  categories={categories ?? []}
                  brands={brands ?? []}
                  priceCols={priceCols}
                  deletingId={deleteMutation.variables}
                  onDelete={(p) => {
                    if (confirm(`Удалить «${p.name}»?`)) deleteMutation.mutate(p.id);
                  }}
                />
              </Card>
            )}
            {data && data.count > filters.pageSize && (
              <Group justify="center">
                <Pagination
                  total={totalPages}
                  value={filters.page}
                  onChange={(page) => patchFilters({ page })}
                />
              </Group>
            )}
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
