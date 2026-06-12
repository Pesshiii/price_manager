import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ArgInput } from '../components/ArgInput';
import type { ArgSpec } from '../types';

const baseSpec: ArgSpec = {
  name: 'x',
  type: 'str',
  label: 'X',
  required: false,
  default: null,
  choices: null,
  help_text: '',
};

describe('ArgInput', () => {
  it('renders text input for str', () => {
    const onChange = vi.fn();
    renderWithProviders(<ArgInput spec={baseSpec} value="" onChange={onChange} />);
    const input = screen.getByLabelText('X');
    fireEvent.change(input, { target: { value: 'abc' } });
    expect(onChange).toHaveBeenCalledWith('abc');
  });

  it('renders checkbox for bool', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <ArgInput spec={{ ...baseSpec, type: 'bool' }} value={false} onChange={onChange} />,
    );
    const cb = screen.getByLabelText('X');
    fireEvent.click(cb);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('renders number input for int', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <ArgInput spec={{ ...baseSpec, type: 'int' }} value="" onChange={onChange} />,
    );
    const input = screen.getByLabelText('X');
    fireEvent.change(input, { target: { value: '7' } });
    expect(onChange).toHaveBeenCalled();
  });

  it('renders textarea for dict[str,str]', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <ArgInput
        spec={{ ...baseSpec, type: 'dict[str,str]' }}
        value="a=b\nc=d"
        onChange={onChange}
      />,
    );
    const ta = screen.getByLabelText('X');
    expect(ta.tagName).toBe('TEXTAREA');
  });

  it('renders select for choices', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <ArgInput
        spec={{ ...baseSpec, choices: ['a', 'b'] }}
        value="a"
        onChange={onChange}
      />,
    );
    // Mantine renders Select as a combobox with the label attached
    expect(screen.getByRole('textbox', { name: /X/ })).toBeInTheDocument();
  });

  it('renders column Select for type=column with available columns', () => {
    renderWithProviders(
      <ArgInput
        spec={{ ...baseSpec, type: 'column' }}
        value=""
        onChange={vi.fn()}
        availableColumns={['name', 'city']}
      />,
    );
    expect(screen.getByRole('textbox', { name: /X/ })).toBeInTheDocument();
  });

  it('renders MultiSelect for type=columns', () => {
    renderWithProviders(
      <ArgInput
        spec={{ ...baseSpec, type: 'columns' }}
        value={['name']}
        onChange={vi.fn()}
        availableColumns={['name', 'city']}
      />,
    );
    // Mantine MultiSelect renders selected values as pills (one or more matches)
    expect(screen.getAllByText('name').length).toBeGreaterThan(0);
  });

  it('renders MappingInput for type=column_mapping', () => {
    renderWithProviders(
      <ArgInput
        spec={{ ...baseSpec, type: 'column_mapping' }}
        value={{ name: 'full_name' }}
        onChange={vi.fn()}
        availableColumns={['name', 'city']}
      />,
    );
    expect(screen.getByDisplayValue('full_name')).toBeInTheDocument();
  });

  it('renders MappingInput for type=value_mapping (text inputs only)', () => {
    renderWithProviders(
      <ArgInput
        spec={{ ...baseSpec, type: 'value_mapping' }}
        value={{ NYC: 'New York' }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByDisplayValue('NYC')).toBeInTheDocument();
    expect(screen.getByDisplayValue('New York')).toBeInTheDocument();
  });
});
