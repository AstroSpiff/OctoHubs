import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getStreamStats } from "@/features/stream-stats/api";
import { defaultStatsFilters } from "@/features/stream-stats/presentation";
import type { StreamStatsFilters } from "@/features/stream-stats/types";
import { isEventBridgeUpdate } from "@/lib/application-events";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

export function useStreamStats() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<StreamStatsFilters>(defaultStatsFilters);
  const stats = useQuery({
    queryKey: ["stream-stats", filters],
    queryFn: () => getStreamStats(filters),
    refetchInterval: 10_000,
  });
  const refreshStats = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["stream-stats"] });
  }, [queryClient]);
  useApplicationEventRefresh(isEventBridgeUpdate, refreshStats);
  function updateFilters(changes: Partial<StreamStatsFilters>) {
    setFilters((current) => ({ ...current, ...changes }));
  }
  function resetFilters() {
    setFilters(defaultStatsFilters);
  }
  return { stats, filters, updateFilters, resetFilters };
}
