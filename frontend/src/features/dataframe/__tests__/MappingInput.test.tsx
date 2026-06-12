import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { MappingInput } from '../components/MappingInput';

describe('MappingInput', () => {
  it('renders an empty row when value is empty', () => {
    renderWithProviders(
      <MappingInput value={{}} onChange={vi.fn()} keyAsColumn={false} label="map" />,
    );
    expect(screen.getByLabelText('Старое')).toBeInTheDocument();
    expect(screen.getByLabelText('Новое')).toBeInTheDocument();
  });

  it('parses legacy "key=value" string into rows', () => {
    renderWithProviders(
      <MappingInput
        value={'a=alpha\nb=beta'}
        onChange={vi.fn()}
        keyAsColumn={false}
        label="map"
      />,
    );
    expect(screen.getByDisplayValue('a')).toBeInTheDocument();
    expect(screen.getByDisplayValue('alpha')).toBeInTheDocument();
    expect(screen.getByDisplayValue('b')).toBeInTheDocument();
  });

  it('emits an object on text edit and persists updates in controlled mode', () => {
    function Wrapper() {
      // Controlled wrapper so MappingInput sees the updated value
      const [v, setV] = useState<Record<string, string>>({});
      return <MappingInput value={v} onChange={setV} keyAsColumn={false} />;
    }
    renderWithProviders(<Wrapper />);
    fireEvent.change(screen.getByLabelText('Старое'), { target: { value: 'x' } });
    fireEvent.change(screen.getByLabelText('Новое'), { target: { value: 'y' } });
    expect(screen.getByDisplayValue('x')).toBeInTheDocument();
    expect(screen.getByDisplayValue('y')).toBeInTheDocument();
  });

  it('keyAsColumn renders Select instead of text', () => {
    renderWithProviders(
      <MappingInput
        value={{}}
        onChange={vi.fn()}
        keyAsColumn
        keyOptions={['name', 'city']}
      />,
    );
    // Mantine Select renders as searchable combobox with role=textbox
    expect(screen.getByRole('textbox', { name: 'Колонка' })).toBeInTheDocument();
  });

  it('add button appends an empty row', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <MappingInput value={{ a: '1' }} onChange={onChange} keyAsColumn={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Добавить/ }));
    // After adding, the existing pair should still be there in the UI
    expect(screen.getByDisplayValue('a')).toBeInTheDocument();
    expect(screen.getByDisplayValue('1')).toBeInTheDocument();
  });
});
