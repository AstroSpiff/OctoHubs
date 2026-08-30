import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "@/lib/http";
import { useApplicationEventRefresh } from "@/lib/use-application-event";
import type { ClearCompletedResult, OperationsSnapshot } from "@/features/operations/types";
import { isUserOperationsRealtimeEvent } from "@/features/users/user-operations-realtime";

const activeRefreshIntervalMs = 2_000;
const idleRefreshIntervalMs = 12_000;

function getUserOperations(): Promise<OperationsSnapshot> {
  return request<OperationsSnapshot>("/api/v1/emby/users/operations");
}

function clearCompletedUserOperations(): Promise<ClearCompletedResult> {
  return request<ClearCompletedResult>("/api/v1/emby/users/operations/clear-completed", { method: "POST" });
}

function useUserOperations() {
  const client = useQueryClient();
  const refresh = useCallback(
    () => client.invalidateQueries({ queryKey: ["users-operations"] }),
    [client],
  );
  const operations = useQuery({
    queryKey: ["users-operations"],
    queryFn: getUserOperations,
    refetchInterval: (query) => query.state.data?.active_count ? activeRefreshIntervalMs : idleRefreshIntervalMs,
  });
  useApplicationEventRefresh(isUserOperationsRealtimeEvent, refresh);
  const clearCompleted = useMutation({
    mutationFn: clearCompletedUserOperations,
    onSuccess: refresh,
  });
  return { operations, clearCompleted };
}

export { useUserOperations };
