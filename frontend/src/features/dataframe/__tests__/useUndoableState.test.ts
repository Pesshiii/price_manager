import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useUndoableState } from '../hooks/useUndoableState';

describe('useUndoableState', () => {
  it('records snapshots on set and allows undo/redo', () => {
    const { result } = renderHook(() => useUndoableState({ count: 0 }));
    expect(result.current.value).toEqual({ count: 0 });
    expect(result.current.canUndo).toBe(false);

    act(() => result.current.set({ count: 1 }));
    act(() => result.current.set({ count: 2 }));
    expect(result.current.value).toEqual({ count: 2 });
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(result.current.value).toEqual({ count: 1 });
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.undo());
    expect(result.current.value).toEqual({ count: 0 });
    expect(result.current.canUndo).toBe(false);

    act(() => result.current.redo());
    expect(result.current.value).toEqual({ count: 1 });
  });

  it('replace does not push snapshot', () => {
    const { result } = renderHook(() => useUndoableState({ v: 0 }));
    act(() => result.current.replace({ v: 5 }));
    expect(result.current.value).toEqual({ v: 5 });
    expect(result.current.canUndo).toBe(false);
  });

  it('respects history limit (oldest evicted)', () => {
    const { result } = renderHook(() => useUndoableState({ n: 0 }, 3));
    act(() => result.current.set({ n: 1 }));
    act(() => result.current.set({ n: 2 }));
    act(() => result.current.set({ n: 3 }));
    act(() => result.current.set({ n: 4 }));
    // History should hold at most 3 prior states
    expect(result.current.history.length).toBe(3);
    // Earliest reachable via undos
    act(() => result.current.undo());
    act(() => result.current.undo());
    act(() => result.current.undo());
    expect(result.current.value).toEqual({ n: 1 }); // {n:0} was evicted
    expect(result.current.canUndo).toBe(false);
  });

  it('clears redo stack on new set', () => {
    const { result } = renderHook(() => useUndoableState({ n: 0 }));
    act(() => result.current.set({ n: 1 }));
    act(() => result.current.undo());
    expect(result.current.canRedo).toBe(true);
    act(() => result.current.set({ n: 9 }));
    expect(result.current.canRedo).toBe(false);
  });

  it('reset clears history', () => {
    const { result } = renderHook(() => useUndoableState({ n: 0 }));
    act(() => result.current.set({ n: 1 }));
    act(() => result.current.reset({ n: 42 }));
    expect(result.current.value).toEqual({ n: 42 });
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });
});
