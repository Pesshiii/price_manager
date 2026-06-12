import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Collapse,
  Divider,
  Group,
  Modal,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import {
  createPricingRule,
  deletePricingRule,
  listPriceTypes,
  listPricingRules,
  updatePricingRule,
} from '../api';
import { pricingKeys } from '../queryKeys';
import type { PricingRule, PricingRuleMode, PricingRuleWritePayload } from '../types';

interface RuleFormState {
  source_price_type: string;
  dest_price_type: string;
  mode: PricingRuleMode;
  markup: number | string;
  increase: number | string;
  fixed_value: number | string;
  priority: number | string;
  price_from: string;
  price_to: string;
  date_from: string;
  date_to: string;
}

const emptyForm: RuleFormState = {
  source_price_type: '',
  dest_price_type: '',
  mode: 'formula',
  markup: '',
  increase: '',
  fixed_value: '',
  priority: 0,
  price_from: '',
  price_to: '',
  date_from: '',
  date_to: '',
};

function ruleToForm(rule: PricingRule): RuleFormState {
  const params = rule.params as Record<string, unknown>;
  return {
    source_price_type: String(rule.source_price_type),
    dest_price_type: String(rule.dest_price_type),
    mode: rule.mode,
    markup: rule.mode === 'formula' ? (params.markup as number ?? '') : '',
    increase: rule.mode === 'formula' ? (params.increase as number ?? '') : '',
    fixed_value: rule.mode === 'fixed' ? (params.value as number ?? '') : '',
    priority: rule.priority,
    price_from: rule.price_from ?? '',
    price_to: rule.price_to ?? '',
    date_from: rule.date_from ? rule.date_from.slice(0, 10) : '',
    date_to: rule.date_to ? rule.date_to.slice(0, 10) : '',
  };
}

function formToPayload(form: RuleFormState, supplierId: number): PricingRuleWritePayload {
  const params: Record<string, unknown> =
    form.mode === 'formula'
      ? {
          markup: form.markup === '' ? 0 : Number(form.markup),
          increase: form.increase === '' ? 0 : Number(form.increase),
        }
      : { value: form.fixed_value === '' ? 0 : Number(form.fixed_value) };

  return {
    supplier: supplierId,
    source_price_type: Number(form.source_price_type),
    dest_price_type: Number(form.dest_price_type),
    mode: form.mode,
    params,
    priority: form.priority === '' ? 0 : Number(form.priority),
    price_from: form.price_from.trim() || null,
    price_to: form.price_to.trim() || null,
    date_from: form.date_from.trim() || null,
    date_to: form.date_to.trim() || null,
  };
}

interface PricingRuleModalProps {
  opened: boolean;
  onClose: () => void;
  supplierId: number;
  editRule?: PricingRule | null;
}

function PricingRuleModal({ opened, onClose, supplierId, editRule }: PricingRuleModalProps) {
  const qc = useQueryClient();
  const [form, setForm] = useState<RuleFormState>(
    editRule ? ruleToForm(editRule) : emptyForm,
  );
  const [conditionsOpen, { toggle: toggleConditions }] = useDisclosure(false);

  // Bug 1 fix: sync form state when modal opens or editRule changes
  useEffect(() => {
    if (opened) {
      setForm(editRule ? ruleToForm(editRule) : emptyForm);
    }
  }, [opened, editRule]);

  const { data: priceTypes } = useQuery({
    queryKey: pricingKeys.priceTypes(),
    queryFn: listPriceTypes,
  });

  const priceTypeOptions = (priceTypes ?? []).map((pt) => ({
    value: String(pt.id),
    label: pt.label,
  }));

  const isEdit = editRule != null;

  const createMutation = useMutation({
    mutationFn: (payload: PricingRuleWritePayload) => createPricingRule(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pricingKeys.rules(supplierId) });
      onClose();
    },
    onError: () => {
      notifications.show({ message: 'Не удалось создать правило', color: 'red' });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: PricingRuleWritePayload }) =>
      updatePricingRule(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pricingKeys.rules(supplierId) });
      onClose();
    },
    onError: () => {
      notifications.show({ message: 'Не удалось обновить правило', color: 'red' });
    },
  });

  function handleSubmit() {
    const payload = formToPayload(form, supplierId);
    if (isEdit) {
      if (!editRule) return;
      updateMutation.mutate({ id: editRule.id, payload });
    } else {
      createMutation.mutate(payload);
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending;
  const isValid =
    form.source_price_type !== '' &&
    form.dest_price_type !== '' &&
    (form.mode === 'formula'
      ? form.markup !== '' || form.increase !== ''
      : form.fixed_value !== '');

  function handleClose() {
    onClose();
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={isEdit ? 'Редактировать правило' : 'Новое правило ценообразования'}
      size="md"
    >
      <Stack>
        <Select
          label="Исходный тип цены"
          placeholder="Выберите тип"
          data={priceTypeOptions}
          value={form.source_price_type || null}
          onChange={(v) => setForm({ ...form, source_price_type: v ?? '' })}
          required
          searchable
        />
        <Select
          label="Целевой тип цены"
          placeholder="Выберите тип"
          data={priceTypeOptions}
          value={form.dest_price_type || null}
          onChange={(v) => setForm({ ...form, dest_price_type: v ?? '' })}
          required
          searchable
        />

        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Режим
          </Text>
          <SegmentedControl
            data={[
              { value: 'formula', label: 'Формула' },
              { value: 'fixed', label: 'Фиксированная' },
            ]}
            value={form.mode}
            onChange={(v) => setForm({ ...form, mode: v as PricingRuleMode })}
          />
        </Stack>

        {form.mode === 'formula' && (
          <Group grow>
            <NumberInput
              label="Наценка %"
              placeholder="0"
              value={form.markup}
              onChange={(v) => setForm({ ...form, markup: v })}
            />
            <NumberInput
              label="Надбавка"
              placeholder="0"
              value={form.increase}
              onChange={(v) => setForm({ ...form, increase: v })}
            />
          </Group>
        )}

        {form.mode === 'fixed' && (
          <NumberInput
            label="Значение"
            placeholder="0"
            value={form.fixed_value}
            onChange={(v) => setForm({ ...form, fixed_value: v })}
            required
          />
        )}

        <NumberInput
          label="Приоритет"
          value={form.priority}
          onChange={(v) => setForm({ ...form, priority: v })}
        />

        <Button
          variant="subtle"
          size="sm"
          onClick={toggleConditions}
          styles={{ root: { alignSelf: 'flex-start' } }}
        >
          {conditionsOpen ? 'Скрыть условия' : 'Добавить условия'}
        </Button>

        <Collapse in={conditionsOpen}>
          <Stack gap="sm">
            <Group grow>
              <NumberInput
                label="Цена от"
                placeholder="—"
                value={form.price_from}
                onChange={(v) => setForm({ ...form, price_from: v === '' ? '' : String(v) })}
                decimalScale={2}
              />
              <NumberInput
                label="Цена до"
                placeholder="—"
                value={form.price_to}
                onChange={(v) => setForm({ ...form, price_to: v === '' ? '' : String(v) })}
                decimalScale={2}
              />
            </Group>
            <Group grow>
              <TextInput
                type="date"
                label="Дата начала"
                value={form.date_from}
                onChange={(e) => setForm({ ...form, date_from: e.currentTarget.value })}
              />
              <TextInput
                type="date"
                label="Дата окончания"
                value={form.date_to}
                onChange={(e) => setForm({ ...form, date_to: e.currentTarget.value })}
              />
            </Group>
          </Stack>
        </Collapse>

        <Group justify="flex-end">
          <Button variant="default" onClick={handleClose}>
            Отмена
          </Button>
          <Button loading={isPending} disabled={!isValid} onClick={handleSubmit}>
            {isEdit ? 'Сохранить' : 'Создать'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

interface PricingRulesSectionProps {
  supplierId: number;
}

export function PricingRulesSection({ supplierId }: PricingRulesSectionProps) {
  const qc = useQueryClient();

  const { data: rules } = useQuery({
    queryKey: pricingKeys.rules(supplierId),
    queryFn: () => listPricingRules(supplierId),
  });

  const { data: priceTypes } = useQuery({
    queryKey: pricingKeys.priceTypes(),
    queryFn: listPriceTypes,
  });

  const priceTypeById = Object.fromEntries((priceTypes ?? []).map((pt) => [pt.id, pt]));

  const [addOpened, { open: openAdd, close: closeAdd }] = useDisclosure(false);
  const [editRule, setEditRule] = useState<PricingRule | null>(null);

  const deleteMutation = useMutation({
    mutationFn: deletePricingRule,
    onSuccess: () => qc.invalidateQueries({ queryKey: pricingKeys.rules(supplierId) }),
    onError: () => {
      notifications.show({ message: 'Не удалось удалить правило', color: 'red' });
    },
  });

  return (
    <>
      <Divider label="Правила ценообразования" labelPosition="left" mt="xl" />

      <Stack gap="sm">
        {(rules ?? []).map((rule) => {
          const srcLabel = priceTypeById[rule.source_price_type]?.label ?? String(rule.source_price_type);
          const dstLabel = priceTypeById[rule.dest_price_type]?.label ?? String(rule.dest_price_type);

          return (
            <Card key={rule.id} withBorder padding="sm">
              <Group justify="space-between">
                <Group gap="xs">
                  <Text size="sm" fw={500}>
                    {srcLabel} → {dstLabel}
                  </Text>
                  <Badge
                    variant="light"
                    color={rule.mode === 'formula' ? 'blue' : 'gray'}
                    size="sm"
                  >
                    {rule.mode === 'formula' ? 'Формула' : 'Фиксированная'}
                  </Badge>
                  <Text size="xs" c="dimmed">
                    Приоритет: {rule.priority}
                  </Text>
                </Group>
                <Group gap="xs">
                  <ActionIcon
                    variant="subtle"
                    onClick={() => setEditRule(rule)}
                    aria-label="Редактировать"
                  >
                    <IconEdit size={16} />
                  </ActionIcon>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    loading={
                      deleteMutation.isPending && deleteMutation.variables === rule.id
                    }
                    onClick={() => {
                      if (confirm('Удалить правило ценообразования?')) {
                        deleteMutation.mutate(rule.id);
                      }
                    }}
                    aria-label="Удалить"
                  >
                    <IconTrash size={16} />
                  </ActionIcon>
                </Group>
              </Group>
            </Card>
          );
        })}

        <Button
          variant="subtle"
          leftSection={<IconPlus size={16} />}
          onClick={openAdd}
          styles={{ root: { alignSelf: 'flex-start' } }}
        >
          Добавить правило
        </Button>
      </Stack>

      <PricingRuleModal
        opened={addOpened}
        onClose={closeAdd}
        supplierId={supplierId}
      />

      <PricingRuleModal
        opened={editRule != null}
        onClose={() => setEditRule(null)}
        supplierId={supplierId}
        editRule={editRule}
      />
    </>
  );
}
