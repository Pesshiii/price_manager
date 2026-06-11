import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { StepList } from '../components/StepList';
import type { Instructions, TransformSpec } from '../types';

const instructions: Instructions = {
  reader: { func: 'read_csv', args: {} },
  transforms: [],
};

const transforms: TransformSpec[] = [
  {
    name: 'select_columns',
    label: 'Оставить колонки',
    args: [
      { name: 'cols', type: 'list[str]', label: 'Колонки', required: true, default: null, choices: null, help_text: '' },
    ],
  },
  {
    name: 'drop_na',
    label: 'Удалить пустые строки',
    args: [],
  },
];

describe('StepList', () => {
  it('renders empty placeholder when there are no steps', () => {
    renderWithProviders(
      <StepList
        steps={[]}
        transforms={transforms}
        selectedIndex={null}
        errorIndex={null}
        instructions={instructions}
        sessionId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onReorder={vi.fn()}
        onChangeArgs={vi.fn()}
        onCommit={vi.fn()}
      />,
    );
    expect(screen.getByText(/Шагов нет/)).toBeInTheDocument();
  });

  it('renders steps in order with badges', () => {
    renderWithProviders(
      <StepList
        steps={[
          { func: 'select_columns', args: { cols: ['a'] } },
          { func: 'drop_na', args: {} },
        ]}
        transforms={transforms}
        selectedIndex={null}
        errorIndex={null}
        instructions={instructions}
        sessionId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onReorder={vi.fn()}
        onChangeArgs={vi.fn()}
        onCommit={vi.fn()}
      />,
    );
    expect(screen.getByTestId('step-0')).toBeInTheDocument();
    expect(screen.getByTestId('step-1')).toBeInTheDocument();
    expect(screen.getByText('Оставить колонки')).toBeInTheDocument();
    expect(screen.getByText('Удалить пустые строки')).toBeInTheDocument();
  });

  it('calls onRemove when delete clicked', () => {
    const onRemove = vi.fn();
    renderWithProviders(
      <StepList
        steps={[{ func: 'drop_na', args: {} }]}
        transforms={transforms}
        selectedIndex={null}
        errorIndex={null}
        instructions={instructions}
        sessionId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
        onRemove={onRemove}
        onReorder={vi.fn()}
        onChangeArgs={vi.fn()}
        onCommit={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByLabelText('Удалить шаг'));
    expect(onRemove).toHaveBeenCalledWith(0);
  });

  it('highlights error step', () => {
    renderWithProviders(
      <StepList
        steps={[
          { func: 'drop_na', args: {} },
          { func: 'select_columns', args: {} },
        ]}
        transforms={transforms}
        selectedIndex={null}
        errorIndex={1}
        instructions={instructions}
        sessionId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onReorder={vi.fn()}
        onChangeArgs={vi.fn()}
        onCommit={vi.fn()}
      />,
    );
    // The error badge appears inside step-1
    const step1 = screen.getByTestId('step-1');
    expect(step1.textContent).toMatch(/ошибка/);
  });
});
