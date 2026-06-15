import { useState } from 'react';
import {
  type ColumnPickerState,
  defaultColumnPickerState,
  loadColumnPickerState,
  saveColumnPickerState,
} from '../persistence';

export function useColumnPicker() {
  const [state, setState] = useState<ColumnPickerState>(
    () => loadColumnPickerState() ?? defaultColumnPickerState(),
  );

  const togglePriceType = (slug: string) => {
    const next: ColumnPickerState = {
      ...state,
      selectedPriceTypes: state.selectedPriceTypes.includes(slug)
        ? state.selectedPriceTypes.filter((s) => s !== slug)
        : [...state.selectedPriceTypes, slug],
    };
    setState(next);
    saveColumnPickerState(next);
  };

  return { selectedPriceTypes: state.selectedPriceTypes, togglePriceType };
}
