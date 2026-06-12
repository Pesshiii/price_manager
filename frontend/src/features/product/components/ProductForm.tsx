import { Button, Group, Select, Stack, Textarea, TextInput, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { useEffect } from 'react';
import { useBrands } from '../hooks/useBrands';
import { useCategories } from '../hooks/useCategories';
import { useCharacteristicTypes } from '../hooks/useCharacteristicTypes';
import type { CharacteristicValue, Product, ProductWritePayload } from '../types';
import { CharacteristicField } from './CharacteristicField';

export interface ProductFormProps {
  initial?: Product;
  submitting?: boolean;
  onSubmit: (payload: ProductWritePayload) => void;
  fieldErrors?: Record<string, string>;
}

interface FormValues {
  sku: string;
  name: string;
  category: number | null;
  brand: number | null;
  description: string;
  status: string;
  characteristics: Record<string, CharacteristicValue | undefined>;
  image_urls: string[];
}

function fromProduct(p?: Product): FormValues {
  return {
    sku: p?.sku ?? '',
    name: p?.name ?? '',
    category: p?.category ?? null,
    brand: p?.brand ?? null,
    description: p?.description ?? '',
    status: p?.status ?? '',
    characteristics: { ...(p?.characteristics ?? {}) },
    image_urls: p?.image_urls ?? [],
  };
}

export function ProductForm({ initial, submitting, onSubmit, fieldErrors }: ProductFormProps) {
  const form = useForm<FormValues>({ initialValues: fromProduct(initial) });
  const { data: categories } = useCategories();
  const { data: brands } = useBrands();
  const categoryId = form.values.category;
  // Per-category fetch is typically small; still ask for a generous page_size
  // to avoid surprising clipping if a category accumulates many EAV types.
  const { data: charTypesPage } = useCharacteristicTypes(
    categoryId !== null ? { category: categoryId, page_size: 500 } : { page_size: 500 },
  );
  const charTypes = charTypesPage?.results ?? [];

  useEffect(() => {
    if (!fieldErrors) return;
    for (const [path, message] of Object.entries(fieldErrors)) {
      form.setFieldError(path, message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fieldErrors]);

  const handleSubmit = form.onSubmit((values) => {
    const characteristics: Record<string, CharacteristicValue> = {};
    for (const [key, value] of Object.entries(values.characteristics)) {
      if (value !== undefined && value !== '') {
        characteristics[key] = value;
      }
    }
    onSubmit({
      sku: values.sku.trim(),
      name: values.name.trim(),
      category: values.category,
      brand: values.brand,
      description: values.description,
      status: values.status,
      characteristics,
      image_urls: values.image_urls,
    });
  });

  return (
    <form onSubmit={handleSubmit}>
      <Stack>
        <Group grow>
          <TextInput label="SKU" required {...form.getInputProps('sku')} />
          <TextInput label="Название" required {...form.getInputProps('name')} />
        </Group>
        <Group grow>
          <Select
            label="Категория"
            placeholder="—"
            clearable
            searchable
            data={(categories ?? []).map((c) => ({
              value: String(c.id),
              label: '— '.repeat(c.level) + c.name,
            }))}
            value={form.values.category !== null ? String(form.values.category) : null}
            onChange={(v) => form.setFieldValue('category', v ? Number(v) : null)}
          />
          <Select
            label="Бренд"
            placeholder="—"
            clearable
            searchable
            data={(brands ?? []).map((b) => ({ value: String(b.id), label: b.name }))}
            value={form.values.brand !== null ? String(form.values.brand) : null}
            onChange={(v) => form.setFieldValue('brand', v ? Number(v) : null)}
          />
          <Select
            label="Статус"
            placeholder="—"
            clearable
            data={['active', 'archived', 'draft']}
            value={form.values.status || null}
            onChange={(v) => form.setFieldValue('status', v ?? '')}
          />
        </Group>
        <Textarea
          label="Описание"
          autosize
          minRows={2}
          {...form.getInputProps('description')}
        />
        {(charTypes?.length ?? 0) > 0 && (
          <Stack gap="xs">
            <Title order={5}>Характеристики</Title>
            {charTypes!.map((type) => (
              <CharacteristicField
                key={type.id}
                type={type}
                value={form.values.characteristics[type.name]}
                error={form.errors[`characteristics.${type.name}`] as string | undefined}
                onChange={(v) =>
                  form.setFieldValue(`characteristics.${type.name}` as never, v as never)
                }
              />
            ))}
          </Stack>
        )}
        <Group justify="flex-end">
          <Button type="submit" loading={submitting}>
            Сохранить
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
