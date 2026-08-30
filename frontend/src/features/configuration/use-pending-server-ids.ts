import { useCallback, useRef, useState } from "react";

function usePendingServerIds() {
  const pendingRef = useRef(new Set<string>());
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());

  const begin = useCallback((serverId: string) => {
    if (pendingRef.current.has(serverId)) return false;
    const next = new Set(pendingRef.current);
    next.add(serverId);
    pendingRef.current = next;
    setPendingIds(next);
    return true;
  }, []);

  const finish = useCallback((serverId: string) => {
    if (!pendingRef.current.has(serverId)) return;
    const next = new Set(pendingRef.current);
    next.delete(serverId);
    pendingRef.current = next;
    setPendingIds(next);
  }, []);

  return { pendingIds, begin, finish };
}

export { usePendingServerIds };
