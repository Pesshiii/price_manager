import {
  Button,
  Checkbox,
  Group,
  Modal,
  MultiSelect,
  Select,
  Stack,
  TagsInput,
  Text,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import {
  updateCharacteristicType,
  type CharacteristicTypeWritePayload,
} from '../api';
import { useCategories } from '../hooks/useCategories';
import { charTypeKeys } from '../queryKeys';
import type { CharacteristicType, ValueType } from '../types';
import { CharacteristicRenameWizard } from './CharacteristicRenameWizard';
import { CharacteristicRetypeWizard } from './CharacteristicRetypeWizard';

interface Props {
  opened: boolean;
  onClose: () => void;
  type: CharacteristicType | null;
}

const VALUE_TYPES: Array<{ value: ValueType; label: string }> = [
  { value: 'string', label: 'Строка' },
  { value: 'integer', label: 'Целое число' },
  { value: 'float', label: 'Число' },
  { value: 'boolean', label: 'Да/Нет' },
  { value: 'choice', label: 'Выбор из списка' },
];

interface FormState {
  name: string;
  label: string;
  value_type: ValueType;
  options: string[];
  unit: string;
  required: boolean;
  categories: number[];
}

function snapshot(t: CharacteristicType): FormState {
  return {
    name: t.name,
    label: t.label,
    value_type: t.value_type,
    options: [...(t.options ?? [])],
    unit: t.unit,
    required: t.required,
    categories: [...(t.categories ?? [])],
  };
}

function arraysEqual(a: unknown[], b: unknown[]) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * Edits one CharacteristicType. The form covers every field, but `name` and
 * `value_type` are handled through the safe-mutation endpoints (a JSONB
 * migration), not through the inline PATCH that backs the other fields.
 *
 * On submit:
 *  1. PATCH everything except `name` / `value_type` (if anything changed).
 *  2. If `name` changed → open the rename wizard.
 *  3. After rename completes (or if name didn't change) → if `value_type`
 *     changed, open the retype wizard.
 *
 * The order matters: retype scans products by the (now new) name.
 */
export function CharacteristicTypeEditModal({ opened, onClose, type }: Props) {
  const qc = useQueryClient();
  const { data: categories } = useCategories();
  const [form, setForm] = useState<FormState | null>(null);
  const [renameTarget, setRenameTarget] = useState<{
    snapshot: CharacteristicType;
    newName: string;
  } | null>(null);
  const [retypeTarget, setRetypeTarget] = useState<{
    snapshot: CharacteristicType;
    newValueType: ValueType;
  } | null>(null);
  /** Pending value_type change kept in stash while the rename wizard runs. */
  const [pendingValueType, setPendingValueType] = useState<ValueType | null>(null);

  useEffect(() => {
    if (opened && type) {
      setForm(snapshot(type));
      setRenameTarget(null);
      setRetypeTarget(null);
      setPendingValueType(null);
    } else if (!opened) {
      setForm(null);
    }
  }, [opened, type]);

  const patchMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: Partial<CharacteristicTypeWritePayload>;
    }) => updateCharacteristicType(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: charTypeKeys.all }),
  });

  // All hooks above; safe to early-return below. Closed/uninitialised renders
  // emit nothing — a placeholder Modal would re-mount the inner form and lose
  // animation state, making it unfindable in tests.
  if (!opened || !type || !form) return null;

  const original = type;
  const nameChanged = form.name.trim() !== original.name && form.name.trim() !== '';
  const valueTypeChanged = form.value_type !== original.value_type;

  function diffSafeFields() {
    const out: Partial<CharacteristicTypeWritePayload> = {};
    if (form!.label !== original.label) out.label = form!.label;
    if (form!.unit !== original.unit) out.unit = form!.unit;
    if (form!.required !== original.required) out.required = form!.required;
    if (!arraysEqual(form!.options, original.options ?? [])) {
      out.options = form!.options;
    }
    if (!arraysEqual(form!.categories, original.categories ?? [])) {
      out.categories = form!.categories;
    }
    return out;
  }

  async function handleSubmit() {
    const safeDiff = diffSafeFields();
    const hasSafeDiff = Object.keys(safeDiff).length > 0;

    try {
      if (hasSafeDiff) {
        await patchMutation.mutateAsync({ id: original.id, payload: safeDiff });
        notifications.show({ message: 'Поля сохранены.', color: 'green' });
      }
    } catch (err) {
      notifications.show({
        message: `Не удалось сохранить: ${(err as Error).message}`,
        color: 'red',
      });
      return;
    }

    // Stash the pending value_type change so the retype wizard fires after
    // rename completes (retype operates on the new key, so rename must go first).
    if (valueTypeChanged) setPendingValueType(form!.value_type);

    if (nameChanged) {
      setRenameTarget({ snapshot: original, newName: form!.name.trim() });
      return;
    }
    if (valueTypeChanged) {
      setRetypeTarget({ snapshot: original, newValueType: form!.value_type });
      return;
    }

    if (hasSafeDiff || !nameChanged) {
      onClose();
    }
  }

  function handleRenameDone(success: boolean) {
    setRenameTarget(null);
    if (!success) {
      setPendingValueType(null);
      return;
    }
    // After successful rename, kick off retype if a value_type change was also requested.
    if (pendingValueType) {
      // Use a fresh snapshot of the type with its new name so the retype wizard
      // scans the right JSONB key. The query invalidation in the rename wizard
      // already refreshed the cache, but for the immediate handoff we patch
      // the snapshot inline.
      setRetypeTarget({
        snapshot: { ...original, name: renameTarget?.newName ?? original.name },
        newValueType: pendingValueType,
      });
      setPendingValueType(null);
    } else {
      onClose();
    }
  }

  function handleRetypeDone() {
    setRetypeTarget(null);
    onClose();
  }

  return (
    <>
      <Modal
        opened={opened && !renameTarget && !retypeTarget}
        onClose={onClose}
        title={`Редактировать «${original.label || original.name}»`}
        size="lg"
      >
        <Stack>
          <Group grow>
            <TextInput
              label="Ключ (slug)"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
              description={
                nameChanged
                  ? 'Будет запущена миграция ключей в JSONB всех товаров.'
                  : undefined
              }
              required
            />
            <TextInput
              label="Метка"
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.currentTarget.value })}
              required
            />
          </Group>
          <Group grow>
            <Select
              label="Тип значения"
              data={VALUE_TYPES}
              value={form.value_type}
              onChange={(v) =>
                setForm({ ...form, value_type: (v ?? 'string') as ValueType })
              }
              allowDeselect={false}
              description={
                valueTypeChanged
                  ? 'Будет запущена миграция значений в JSONB всех товаров.'
                  : undefined
              }
            />
            <TextInput
              label="Единица"
              value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.currentTarget.value })}
            />
          </Group>
          {form.value_type === 'choice' && (
            <TagsInput
              label="Варианты"
              value={form.options}
              onChange={(options) => setForm({ ...form, options })}
            />
          )}
          <MultiSelect
            label="Категории"
            searchable
            data={(categories ?? []).map((c) => ({
              value: String(c.id),
              label: '— '.repeat(c.level) + c.name,
            }))}
            value={form.categories.map(String)}
            onChange={(values) =>
              setForm({ ...form, categories: values.map((v) => Number(v)) })
            }
          />
          <Checkbox
            label="Обязательная"
            checked={form.required}
            onChange={(e) =>
              setForm({ ...form, required: e.currentTarget.checked })
            }
          />

          {(nameChanged || valueTypeChanged) && (
            <Text size="xs" c="dimmed">
              При сохранении эти миграционные изменения будут проведены
              отдельной фоновой задачей и могут занять время.
            </Text>
          )}

          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Отмена
            </Button>
            <Button
              onClick={handleSubmit}
              loading={patchMutation.isPending}
              disabled={!form.name.trim() || !form.label.trim()}
            >
              Сохранить
            </Button>
          </Group>
        </Stack>
      </Modal>

      {renameTarget && (
        <CharacteristicRenameWizard
          opened
          onClose={() => handleRenameDone(false)}
          type={renameTarget.snapshot}
          newName={renameTarget.newName}
          onCompleted={handleRenameDone}
        />
      )}
      {retypeTarget && (
        <CharacteristicRetypeWizard
          opened
          onClose={handleRetypeDone}
          type={retypeTarget.snapshot}
          newValueType={retypeTarget.newValueType}
          onCompleted={handleRetypeDone}
        />
      )}
    </>
  );
}
