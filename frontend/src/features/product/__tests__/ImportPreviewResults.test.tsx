import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import {
  ImportPreviewResults,
  normalizeRowErrors,
} from '../components/import/ImportPreviewResults';
import type { ImportPreviewResult } from '../types';

describe('normalizeRowErrors', () => {
  it('keeps an array of strings as-is', () => {
    expect(normalizeRowErrors(['sku: required', 'name: too long'])).toEqual([
      'sku: required',
      'name: too long',
    ]);
  });

  it('flattens a DRF-style object {field: [msg]} into "field: msg" lines', () => {
    expect(
      normalizeRowErrors({ sku: ['required'], characteristics: ['color: bad'] }),
    ).toEqual(['sku: required', 'characteristics: color: bad']);
  });

  it('accepts a single string value per field', () => {
    expect(normalizeRowErrors({ sku: 'required' })).toEqual(['sku: required']);
  });

  it('omits the prefix for non_field_errors', () => {
    expect(normalizeRowErrors({ non_field_errors: ['row is empty'] })).toEqual([
      'row is empty',
    ]);
  });

  it('wraps a bare string into a single-element list', () => {
    expect(normalizeRowErrors('boom')).toEqual(['boom']);
  });

  it('returns [] for null/undefined/garbage', () => {
    expect(normalizeRowErrors(null)).toEqual([]);
    expect(normalizeRowErrors(undefined)).toEqual([]);
    expect(normalizeRowErrors({ sku: null as unknown as string })).toEqual([]);
  });
});

describe('ImportPreviewResults rendering', () => {
  it('renders mixed-shape errors without crashing', () => {
    const result: ImportPreviewResult = {
      total: 3,
      returned: 3,
      valid: 1,
      invalid: 2,
      rows: [
        { index: 0, payload: { sku: 'A' }, errors: [] },
        { index: 1, payload: { sku: 'B' }, errors: { sku: ['required'] } },
        { index: 2, payload: { sku: 'C' }, errors: ['name: missing'] },
      ],
    };
    renderWithProviders(<ImportPreviewResults result={result} />);
    expect(screen.getByText('Валидных: 1')).toBeInTheDocument();
    expect(screen.getByText('С ошибками: 2')).toBeInTheDocument();
    expect(screen.getByText('sku: required')).toBeInTheDocument();
    expect(screen.getByText('name: missing')).toBeInTheDocument();
  });
});
