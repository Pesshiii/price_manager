import { afterEach, describe, expect, it } from 'vitest';
import {
  STORAGE_KEY,
  clearPersistedState,
  defaultPersistedState,
  loadPersistedState,
  savePersistedState,
} from '../persistence';

afterEach(() => {
  localStorage.clear();
});

describe('product import persistence', () => {
  it('returns null when storage is empty', () => {
    expect(loadPersistedState()).toBeNull();
  });

  it('roundtrips a saved snapshot', () => {
    const state = {
      ...defaultPersistedState(),
      mode: 'adhoc' as const,
      step: 1 as const,
      sessionId: 'abc',
      columns: ['sku', 'name'],
      mapping: { sku: { column: 'sku' } },
    };
    savePersistedState(state);
    const loaded = loadPersistedState();
    expect(loaded).not.toBeNull();
    expect(loaded?.sessionId).toBe('abc');
    expect(loaded?.columns).toEqual(['sku', 'name']);
    expect(loaded?.mapping).toEqual({ sku: { column: 'sku' } });
    expect(loaded?.step).toBe(1);
  });

  it('returns null and wipes on garbage', () => {
    localStorage.setItem(STORAGE_KEY, '{not json');
    expect(loadPersistedState()).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns null and wipes on version mismatch', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 0, mode: 'saved' }));
    expect(loadPersistedState()).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('clearPersistedState removes the key', () => {
    savePersistedState(defaultPersistedState());
    clearPersistedState();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('fills missing fields with defaults', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 3, sessionId: 'x' }));
    const loaded = loadPersistedState();
    expect(loaded?.sessionId).toBe('x');
    expect(loaded?.mode).toBe('saved');
    expect(loaded?.columns).toEqual([]);
    expect(loaded?.previewJobId).toBeNull();
    expect(loaded?.commitJobId).toBeNull();
  });
});
