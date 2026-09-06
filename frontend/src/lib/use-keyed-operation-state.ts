import { useCallback, useRef, useState } from "react";

function useKeyedOperationState() {
  const pendingCountsRef = useRef(new Map<string, number>());
  const [pendingKeys, setPendingKeys] = useState<ReadonlySet<string>>(() => new Set());
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const begin = useCallback((keys: readonly string[]) => {
    const counts = new Map(pendingCountsRef.current);
    for (const key of keys) counts.set(key, (counts.get(key) || 0) + 1);
    pendingCountsRef.current = counts;
    setPendingKeys(new Set(counts.keys()));
    setErrors((current) => {
      if (!keys.some((key) => key in current)) return current;
      const next = { ...current };
      for (const key of keys) delete next[key];
      return next;
    });
  }, []);

  const fail = useCallback((keys: readonly string[], error: unknown) => {
    const message = error instanceof Error ? error.message : "Operazione non riuscita";
    setErrors((current) => {
      const next = { ...current };
      for (const key of keys) next[key] = message;
      return next;
    });
  }, []);

  const finish = useCallback((keys: readonly string[]) => {
    const counts = new Map(pendingCountsRef.current);
    for (const key of keys) {
      const remaining = (counts.get(key) || 0) - 1;
      if (remaining > 0) counts.set(key, remaining);
      else counts.delete(key);
    }
    pendingCountsRef.current = counts;
    setPendingKeys(new Set(counts.keys()));
  }, []);

  const clear = useCallback((keys?: readonly string[]) => {
    setErrors((current) => {
      if (!keys) return {};
      if (!keys.some((key) => key in current)) return current;
      const next = { ...current };
      for (const key of keys) delete next[key];
      return next;
    });
  }, []);

  const isPending = useCallback(
    (key: string) => (pendingCountsRef.current.get(key) || 0) > 0,
    [],
  );

  return { begin, clear, errors, fail, finish, isPending, pendingKeys };
}

export { useKeyedOperationState };
