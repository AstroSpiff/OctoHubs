import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  completedLatestOperations,
  hasActiveLatestWorkflow,
} from "@/features/emby-latest/latest-operation-refresh";
import { getOperations } from "@/features/operations/api";
import type { Operation } from "@/features/operations/types";

const activeRefreshIntervalMs = 2_000;
const idleRefreshIntervalMs = 12_000;

function useLatestOperationRefresh(onCompleted: () => void) {
  const previousRef = useRef<Operation[] | undefined>(undefined);
  const operations = useQuery({
    queryKey: ["operations"],
    queryFn: getOperations,
    refetchInterval: (query) =>
      query.state.data?.active_count
        ? activeRefreshIntervalMs
        : idleRefreshIntervalMs,
  });

  useEffect(() => {
    const current = operations.data?.operations;
    if (!current) return;
    const previous = previousRef.current;
    previousRef.current = current;
    if (!previous || !completedLatestOperations(previous, current).length) return;
    onCompleted();
  }, [onCompleted, operations.data]);

  return {
    workflowActive: hasActiveLatestWorkflow(operations.data?.operations || []),
    refreshOperations: operations.refetch,
  };
}

export { useLatestOperationRefresh };
