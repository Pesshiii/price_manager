import {
  ActionIcon,
  Autocomplete,
  Button,
  Divider,
  Group,
  Modal,
  NumberInput,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { notifications } from '@mantine/notifications';
import {
  createMarkupRule,
  createMarkupSet,
  deleteMarkupRule,
  updateMarkupRule,
  updateMarkupSet,
} from '../api';
import { supplierKeys } from '../queryKeys';
import type { FeedMarkupRule, FeedMarkupSet } from '../types';

interface RuleRow {
  id?: number;
  price_from: string;
  price_to: string;
  markup: string;
  increase: string;
}

interface Props {
  opened: boolean;
  onClose: () => void;
  mappingId: number;
  availableColumns: string[];
  existing?: FeedMarkupSet;
}

function emptyRule(): RuleRow {
  return { price_from: '', price_to: '', markup: '0', increase: '0' };
}

function toRow(r: FeedMarkupRule): RuleRow {
  return {
    id: r.id,
    price_from: r.price_from ?? '',
    price_to: r.price_to ?? '',
    markup: r.markup,
    increase: r.increase,
  };
}

export function MarkupSetModal({ opened, onClose, mappingId, availableColumns, existing }: Props) {
  const qc = useQueryClient();

  const [name, setName] = useState(existing?.name ?? '');
  const [priceColumn, setPriceColumn] = useState(existing?.price_column ?? '');
  const [outputColumn, setOutputColumn] = useState(existing?.output_column ?? '');
  const [rules, setRules] = useState<RuleRow[]>(existing?.rules.map(toRow) ?? []);

  const isEdit = existing !== undefined;

  const saveMutation = useMutation({
    mutationFn: async () => {
      let setId: number;

      if (isEdit) {
        await updateMarkupSet(existing.id, {
          name: name.trim(),
          price_column: priceColumn.trim(),
          output_column: outputColumn.trim(),
        });
        setId = existing.id;
      } else {
        const created = await createMarkupSet({
          feed_mapping: mappingId,
          name: name.trim(),
          price_column: priceColumn.trim(),
          output_column: outputColumn.trim(),
        });
        setId = created.id;
      }

      const existingIds = new Set((existing?.rules ?? []).map((r) => r.id));
      const keptIds = new Set(rules.filter((r) => r.id).map((r) => r.id!));

      // Delete removed rules
      for (const id of existingIds) {
        if (!keptIds.has(id)) {
          await deleteMarkupRule(id);
        }
      }

      // Create or update rules in order
      for (let i = 0; i < rules.length; i++) {
        const row = rules[i];
        const order = (i + 1) * 10;
        const payload = {
          order,
          price_from: row.price_from.trim() === '' ? null : row.price_from.trim(),
          price_to: row.price_to.trim() === '' ? null : row.price_to.trim(),
          markup: row.markup || '0',
          increase: row.increase || '0',
        };
        if (row.id) {
          await updateMarkupRule(row.id, payload);
        } else {
          await createMarkupRule({ markup_set: setId, ...payload });
        }
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: supplierKeys.markupSets(mappingId) });
      notifications.show({ message: 'Набор наценок сохранён', color: 'green' });
      onClose();
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: unknown } })?.response?.data ?? e;
      notifications.show({
        message: typeof msg === 'string' ? msg : JSON.stringify(msg),
        color: 'red',
      });
    },
  });

  const addRule = () => setRules((prev) => [...prev, emptyRule()]);

  const removeRule = (index: number) =>
    setRules((prev) => prev.filter((_, i) => i !== index));

  const moveRule = (index: number, direction: -1 | 1) => {
    const next = index + direction;
    if (next < 0 || next >= rules.length) return;
    setRules((prev) => {
      const copy = [...prev];
      [copy[index], copy[next]] = [copy[next], copy[index]];
      return copy;
    });
  };

  const updateField = (index: number, field: keyof RuleRow, value: string) =>
    setRules((prev) => prev.map((r, i) => (i === index ? { ...r, [field]: value } : r)));

  const canSubmit = name.trim().length > 0 && priceColumn.trim().length > 0 && outputColumn.trim().length > 0;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={isEdit ? 'Редактировать набор наценок' : 'Новый набор наценок'}
      size="xl"
    >
      <Stack gap="md">
        <TextInput
          label="Название"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
        />

        <Group grow>
          <Autocomplete
            label="Колонка источника цены"
            description="price_column из вывода пайплайна"
            data={availableColumns}
            value={priceColumn}
            onChange={setPriceColumn}
            required
          />
          <Autocomplete
            label="Колонка результата"
            description="output_column в SupplierFeedEntry.data"
            data={availableColumns}
            value={outputColumn}
            onChange={setOutputColumn}
            required
          />
        </Group>

        <Divider label="Правила наценки" labelPosition="left" />

        {rules.length === 0 ? (
          <Text size="sm" c="dimmed">
            Нет правил — если нет покрывающего правила, output_column не записывается.
          </Text>
        ) : (
          <Table withTableBorder withColumnBorders fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={40} />
                <Table.Th>Цена от</Table.Th>
                <Table.Th>Цена до</Table.Th>
                <Table.Th>Наценка %</Table.Th>
                <Table.Th>Надбавка</Table.Th>
                <Table.Th w={40} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rules.map((row, i) => (
                <Table.Tr key={i}>
                  <Table.Td>
                    <Stack gap={2}>
                      <ActionIcon
                        size="xs"
                        variant="subtle"
                        disabled={i === 0}
                        onClick={() => moveRule(i, -1)}
                      >
                        <IconArrowUp size={12} />
                      </ActionIcon>
                      <ActionIcon
                        size="xs"
                        variant="subtle"
                        disabled={i === rules.length - 1}
                        onClick={() => moveRule(i, 1)}
                      >
                        <IconArrowDown size={12} />
                      </ActionIcon>
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    <NumberInput
                      placeholder="∞"
                      value={row.price_from}
                      onChange={(v) => updateField(i, 'price_from', String(v))}
                      min={0}
                      decimalScale={4}
                      size="xs"
                    />
                  </Table.Td>
                  <Table.Td>
                    <NumberInput
                      placeholder="∞"
                      value={row.price_to}
                      onChange={(v) => updateField(i, 'price_to', String(v))}
                      min={0}
                      decimalScale={4}
                      size="xs"
                    />
                  </Table.Td>
                  <Table.Td>
                    <NumberInput
                      value={row.markup}
                      onChange={(v) => updateField(i, 'markup', String(v))}
                      decimalScale={4}
                      size="xs"
                    />
                  </Table.Td>
                  <Table.Td>
                    <NumberInput
                      value={row.increase}
                      onChange={(v) => updateField(i, 'increase', String(v))}
                      decimalScale={4}
                      size="xs"
                    />
                  </Table.Td>
                  <Table.Td>
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      color="red"
                      onClick={() => removeRule(i)}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}

        <Button
          variant="subtle"
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={addRule}
          w="fit-content"
        >
          Добавить правило
        </Button>

        <Group justify="flex-end" mt="sm">
          <Button variant="default" onClick={onClose}>
            Отмена
          </Button>
          <Button
            disabled={!canSubmit}
            loading={saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            Сохранить
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
