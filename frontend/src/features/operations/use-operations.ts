import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { clearCompletedOperations, getOperations, stopWorkflow } from "@/features/operations/api";

const activeRefreshIntervalMs = 2_000;
const idleRefreshIntervalMs = 12_000;

export function useOperations() {
  const queryClient = useQueryClient();
  const operations = useQuery({
    queryKey: ["operations"],
    queryFn: getOperations,
    refetchInterval: (query) => query.state.data?.active_count ? activeRefreshIntervalMs : idleRefreshIntervalMs,
  });
  const clearCompleted = useMutation({
    mutationFn: clearCompletedOperations,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["operations"] });
    },
  });

  const stopActiveWorkflow = useMutation({
    mutationFn: stopWorkflow,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["operations"] });
    },
  });

  return { operations, clearCompleted, stopActiveWorkflow };
}
