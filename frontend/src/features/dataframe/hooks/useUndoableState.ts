import { useCallback, useRef, useState } from 'react';

export interface UndoableState<T> {
  value: T;
  set: (next: T | ((prev: T) => T)) => void;
  replace: (next: T | ((prev: T) => T)) => void;
  reset: (next: T) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  history: T[];
}

const DEFAULT_LIMIT = 50;

function resolve<T>(next: T | ((prev: T) => T), prev: T): T {
  return typeof next === 'function' ? (next as (p: T) => T)(prev) : next;
}

export function useUndoableState<T>(initial: T, limit = DEFAULT_LIMIT): UndoableState<T> {
  const [past, setPast] = useState<T[]>([]);
  const [present, setPresent] = useState<T>(initial);
  const [future, setFuture] = useState<T[]>([]);
  const limitRef = useRef(limit);
  limitRef.current = limit;

  const set = useCallback((next: T | ((prev: T) => T)) => {
    setPresent((prev) => {
      const resolved = resolve(next, prev);
      setPast((p) => {
        const newPast = [...p, prev];
        return newPast.length > limitRef.current ? newPast.slice(-limitRef.current) : newPast;
      });
      setFuture([]);
      return resolved;
    });
  }, []);

  const replace = useCallback((next: T | ((prev: T) => T)) => {
    setPresent((prev) => resolve(next, prev));
  }, []);

  const undo = useCallback(() => {
    setPast((p) => {
      if (p.length === 0) return p;
      const previous = p[p.length - 1];
      setFuture((f) => [present, ...f]);
      setPresent(previous);
      return p.slice(0, -1);
    });
  }, [present]);

  const redo = useCallback(() => {
    setFuture((f) => {
      if (f.length === 0) return f;
      const [next, ...rest] = f;
      setPast((p) => [...p, present]);
      setPresent(next);
      return rest;
    });
  }, [present]);

  const reset = useCallback((next: T) => {
    setPast([]);
    setFuture([]);
    setPresent(next);
  }, []);

  return {
    value: present,
    set,
    replace,
    reset,
    undo,
    redo,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
    history: past,
  };
}
