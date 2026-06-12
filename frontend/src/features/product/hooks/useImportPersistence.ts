import { useEffect } from 'react';
import { useDebouncedValue } from '@/features/dataframe/hooks/useDebouncedValue';
import { savePersistedState, type ImportPersistedState } from '../persistence';

export function useImportPersistence(state: ImportPersistedState, debounceMs = 200): void {
  const debounced = useDebouncedValue(state, debounceMs);
  useEffect(() => {
    savePersistedState(debounced);
  }, [debounced]);
}
