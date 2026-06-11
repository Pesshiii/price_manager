import { describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { CharacteristicField } from '../components/CharacteristicField';
import type { CharacteristicType, CharacteristicValue } from '../types';

function makeType(overrides: Partial<CharacteristicType> = {}): CharacteristicType {
  return {
    id: 1,
    name: 'color',
    label: 'Цвет',
    value_type: 'string',
    options: [],
    unit: '',
    required: false,
    categories: [],
    ...overrides,
  };
}

function Controlled({
  type,
  spy,
  initial,
}: {
  type: CharacteristicType;
  spy: (v: CharacteristicValue | undefined) => void;
  initial?: CharacteristicValue;
}) {
  const [value, setValue] = useState<CharacteristicValue | undefined>(initial);
  return (
    <CharacteristicField
      type={type}
      value={value}
      onChange={(v) => {
        setValue(v);
        spy(v);
      }}
    />
  );
}

describe('CharacteristicField', () => {
  it('renders text input for string and emits string', async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    renderWithProviders(<Controlled type={makeType()} spy={spy} />);
    await user.type(screen.getByRole('textbox', { name: 'Цвет' }), 'red');
    expect(spy).toHaveBeenLastCalledWith('red');
  });

  it('coerces integer to number', async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    renderWithProviders(
      <Controlled
        type={makeType({ name: 'qty', label: 'Кол-во', value_type: 'integer' })}
        spy={spy}
      />,
    );
    await user.type(screen.getByRole('textbox', { name: 'Кол-во' }), '42');
    const last = spy.mock.calls.at(-1)?.[0];
    expect(typeof last).toBe('number');
    expect(last).toBe(42);
  });

  it('emits boolean via Switch', async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    renderWithProviders(
      <Controlled
        type={makeType({ name: 'avail', label: 'В наличии', value_type: 'boolean' })}
        spy={spy}
        initial={false}
      />,
    );
    await user.click(screen.getByRole('switch', { name: 'В наличии' }));
    expect(spy).toHaveBeenCalledWith(true);
  });

  it('renders Select for choice and emits selected option', async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    renderWithProviders(
      <Controlled
        type={makeType({
          name: 'size',
          label: 'Размер',
          value_type: 'choice',
          options: ['S', 'M', 'L'],
        })}
        spy={spy}
      />,
    );
    await user.click(screen.getByRole('textbox', { name: 'Размер' }));
    await user.click(await screen.findByRole('option', { name: 'M' }));
    expect(spy).toHaveBeenCalledWith('M');
  });

  it('shows unit suffix in label', () => {
    renderWithProviders(
      <Controlled
        type={makeType({ label: 'Длина', unit: 'мм', value_type: 'integer' })}
        spy={vi.fn()}
      />,
    );
    expect(screen.getByRole('textbox', { name: 'Длина (мм)' })).toBeInTheDocument();
  });
});
