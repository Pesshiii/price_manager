import { Button, Divider, Group, NumberInput, Select, Stack, Text, TextInput } from '@mantine/core';
import type { PriceType } from '@/features/pricing/types';
import { useBrands } from '../hooks/useBrands';
import { useCategories } from '../hooks/useCategories';
import { useProductFacets } from '../hooks/useProductFacets';
import type { ProductFilters } from '../types';
import { FacetGroup } from './FacetGroup';

export interface ProductFiltersSidebarProps {
  filters: ProductFilters;
  patchFilters: (patch: Partial<ProductFilters>) => void;
  toggleCharValue: (name: string, value: string) => void;
  resetFilters: () => void;
  priceTypes: PriceType[];
}

export function ProductFiltersSidebar({
  filters,
  patchFilters,
  toggleCharValue,
  resetFilters,
  priceTypes,
}: ProductFiltersSidebarProps) {
  const { data: categories } = useCategories();
  const { data: brands } = useBrands();
  // The facets endpoint is self-describing (label/unit/value_type embedded per
  // group), so we no longer need to fetch the full CharacteristicType list to
  // render this sidebar — which mattered once the catalog grew past a few
  // hundred types (frozen browser otherwise).
  const { data: facets } = useProductFacets(filters);

  return (
    <Stack gap="md">
      <TextInput
        label="Поиск"
        placeholder="Название или SKU"
        value={filters.q ?? ''}
        onChange={(e) => patchFilters({ q: e.currentTarget.value || undefined })}
      />
      <Select
        label="Категория"
        placeholder="Все"
        data={(categories ?? []).map((c) => ({
          value: String(c.id),
          label: '— '.repeat(c.level) + c.name,
        }))}
        value={filters.category !== undefined ? String(filters.category) : null}
        onChange={(v) => patchFilters({ category: v ? Number(v) : undefined })}
        clearable
        searchable
      />
      <Select
        label="Бренд"
        placeholder="Все"
        data={(brands ?? []).map((b) => ({ value: String(b.id), label: b.name }))}
        value={filters.brand !== undefined ? String(filters.brand) : null}
        onChange={(v) => patchFilters({ brand: v ? Number(v) : undefined })}
        clearable
        searchable
      />
      <Select
        label="Статус"
        placeholder="Любой"
        data={['active', 'archived', 'draft']}
        value={filters.status ?? null}
        onChange={(v) => patchFilters({ status: v ?? undefined })}
        clearable
      />
      <Divider />
      {Object.entries(facets ?? {}).map(([name, group]) => (
        <FacetGroup
          key={name}
          label={group.label}
          unit={group.unit}
          buckets={group.buckets}
          selected={filters.chars[name] ?? []}
          onToggle={(value) => toggleCharValue(name, value)}
        />
      ))}
      <Divider my="sm" />
      <Text size="sm" fw={500} mb="xs">Фильтр по цене</Text>
      <Select
        placeholder="Тип цены"
        data={priceTypes.map((pt) => ({ value: pt.name, label: pt.label }))}
        value={filters.price_type ?? null}
        onChange={(val) =>
          patchFilters({ price_type: val ?? undefined, price_min: undefined, price_max: undefined })
        }
        clearable
        size="sm"
      />
      {filters.price_type && (
        <Group gap="xs" mt="xs">
          <NumberInput
            placeholder="От"
            value={filters.price_min ?? ''}
            onChange={(val) =>
              patchFilters({ price_min: typeof val === 'number' ? val : undefined })
            }
            min={0}
            size="sm"
            style={{ flex: 1 }}
          />
          <NumberInput
            placeholder="До"
            value={filters.price_max ?? ''}
            onChange={(val) =>
              patchFilters({ price_max: typeof val === 'number' ? val : undefined })
            }
            min={0}
            size="sm"
            style={{ flex: 1 }}
          />
        </Group>
      )}
      <Button variant="subtle" onClick={resetFilters}>
        Сбросить
      </Button>
    </Stack>
  );
}
