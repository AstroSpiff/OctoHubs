import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getOperations } from "@/features/operations/api";
import { isActiveOperation } from "@/features/operations/presentation";
import type { Operation } from "@/features/operations/types";

const operationRefreshIntervalMs = 1_500;

type CollectionOperationScope =
  | { type: "collection"; collectionId: string }
  | { type: "all" };

type TrackedOperation = CollectionOperationScope & {
  operationId: string;
};

function completedCollectionOperations(
  tracked: TrackedOperation[],
  operations: Operation[],
): TrackedOperation[] {
  const operationById = new Map(
    operations.map((operation) => [operation.id, operation]),
  );
  return tracked.filter((entry) => {
    const operation = operationById.get(entry.operationId);
    return !operation || !isActiveOperation(operation);
  });
}

function useCollectionOperationWatch(onCompleted: () => void) {
  const [tracked, setTracked] = useState<TrackedOperation[]>([]);
  const completedRef = useRef(new Set<string>());
  const operationIds = useMemo(
    () => tracked.map((entry) => entry.operationId).sort(),
    [tracked],
  );
  const operationIdsKey = operationIds.join(",");
  const operations = useQuery({
    queryKey: ["collection-operation-watch", operationIdsKey],
    queryFn: getOperations,
    enabled: operationIds.length > 0,
    refetchInterval: operationRefreshIntervalMs,
  });

  const track = useCallback(
    (operationId: string | undefined, scope: CollectionOperationScope) => {
      if (!operationId) return;
      setTracked((current) =>
        current.some((entry) => entry.operationId === operationId)
          ? current
          : [...current, { operationId, ...scope }],
      );
    },
    [],
  );

  useEffect(() => {
    if (!operations.isSuccess) return;
    const completed = completedCollectionOperations(
      tracked,
      operations.data?.operations || [],
    ).filter((entry) => !completedRef.current.has(entry.operationId));
    if (!completed.length) return;

    completed.forEach((entry) => completedRef.current.add(entry.operationId));
    setTracked((current) =>
      current.filter(
        (entry) => !completed.some((done) => done.operationId === entry.operationId),
      ),
    );
    onCompleted();
  }, [onCompleted, operations.data, operations.isSuccess, tracked]);

  return {
    track,
    isSyncingAll: tracked.some((entry) => entry.type === "all"),
    isSyncingCollection: (collectionId: string) =>
      tracked.some(
        (entry) =>
          entry.type === "collection" && entry.collectionId === collectionId,
      ),
  };
}

export {
  completedCollectionOperations,
  useCollectionOperationWatch,
  type CollectionOperationScope,
  type TrackedOperation,
};
