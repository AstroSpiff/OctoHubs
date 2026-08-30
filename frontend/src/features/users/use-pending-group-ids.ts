import { useCallback, useRef, useState } from "react";

function usePendingGroupIds() {
  const pendingRef = useRef(new Set<string>());
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());

  const begin = useCallback((groupId: string) => {
    if (pendingRef.current.has(groupId)) return false;
    const next = new Set(pendingRef.current);
    next.add(groupId);
    pendingRef.current = next;
    setPendingIds(next);
    return true;
  }, []);

  const finish = useCallback((groupId: string) => {
    if (!pendingRef.current.has(groupId)) return;
    const next = new Set(pendingRef.current);
    next.delete(groupId);
    pendingRef.current = next;
    setPendingIds(next);
  }, []);

  return { pendingIds, begin, finish };
}

export { usePendingGroupIds };
