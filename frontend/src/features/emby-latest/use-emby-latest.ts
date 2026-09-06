import { useCallback, useEffect, useState } from "react";
import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  clearLatestState,
  deleteLatestPreset,
  deleteLatestRule,
  enrichLatest,
  getLatestConfiguration,
  getLatestProgress,
  getLatestSnapshot,
  notifyLatest,
  previewLatest,
  refreshLatest,
  resetLatest,
  resetLatestScanTracking,
  saveLatestPreset,
  saveLatestRule,
  setLatestRuleEnabled,
  startLatestWorkflow,
} from "@/features/emby-latest/api";
import { latestFetchLimits } from "@/features/emby-latest/latest-fetch-limits";
import { useLatestOperationRefresh } from "@/features/emby-latest/use-latest-operation-refresh";
import {
  isLatestRealtimeEvent,
  latestRealtimeTargets,
} from "@/features/emby-latest/latest-realtime";
import type {
  LatestPreviewRequest,
} from "@/features/emby-latest/types";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

const latestConfigurationMutationKey = ["emby-latest-configuration-mutation"];

function useEmbyLatest() {
  const client = useQueryClient();
  const [refreshPending, setRefreshPending] = useState(false);
  const configuration = useQuery({
    queryKey: ["emby-latest-configuration"],
    queryFn: getLatestConfiguration,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const fetchLimits = latestFetchLimits(
    configuration.data?.settings.limits,
    configuration.data?.servers.length,
  );
  const snapshot = useQuery({
    queryKey: ["emby-latest", fetchLimits],
    queryFn: () => getLatestSnapshot(fetchLimits),
    enabled: Boolean(configuration.data?.success),
    refetchInterval: (query) => (query.state.data?.refreshing ? 2_500 : 30_000),
  });
  const progressEnabled = refreshPending || Boolean(snapshot.data?.refreshing);
  const progress = useQuery({
    queryKey: ["emby-latest-progress"],
    queryFn: getLatestProgress,
    enabled: progressEnabled,
    refetchInterval: progressEnabled ? 2_500 : false,
  });
  const refreshSnapshot = useCallback(
    () => client.invalidateQueries({ queryKey: ["emby-latest"] }),
    [client],
  );
  const refreshConfiguration = useCallback(
    () => client.invalidateQueries({ queryKey: ["emby-latest-configuration"] }),
    [client],
  );
  const refreshFromRealtime = useCallback(
    (event: Parameters<typeof latestRealtimeTargets>[0]) => {
      const targets = latestRealtimeTargets(event);
      if (targets.includes("configuration")) {
        void refreshConfiguration();
      }
      if (targets.includes("snapshot")) {
        void Promise.all([
          refreshSnapshot(),
          client.invalidateQueries({ queryKey: ["emby-latest-progress"] }),
        ]);
      }
    },
    [client, refreshConfiguration, refreshSnapshot],
  );
  useApplicationEventRefresh(isLatestRealtimeEvent, refreshFromRealtime);
  const refreshAfterOperation = useCallback(() => {
    setRefreshPending(false);
    void refreshSnapshot();
    void refreshConfiguration();
  }, [refreshConfiguration, refreshSnapshot]);
  const latestOperations = useLatestOperationRefresh(refreshAfterOperation);
  const configurationBusy =
    useIsMutating({ mutationKey: latestConfigurationMutationKey }) > 0;
  const refresh = useMutation({
    mutationFn: refreshLatest,
    onSuccess: (result) => {
      setRefreshPending(Boolean(result.refreshing));
      refreshSnapshot();
    },
  });
  const notify = useMutation({
    mutationFn: notifyLatest,
    onSuccess: refreshSnapshot,
  });
  const workflow = useMutation({
    mutationFn: startLatestWorkflow,
    onSuccess: () => {
      void latestOperations.refreshOperations();
      refreshSnapshot();
    },
  });
  const preset = useMutation({
    mutationKey: latestConfigurationMutationKey,
    mutationFn: saveLatestPreset,
    onSuccess: refreshConfiguration,
  });
  const removePreset = useMutation({
    mutationKey: latestConfigurationMutationKey,
    mutationFn: deleteLatestPreset,
    onSuccess: refreshConfiguration,
  });
  const rule = useMutation({
    mutationKey: latestConfigurationMutationKey,
    mutationFn: saveLatestRule,
    onSuccess: refreshConfiguration,
  });
  const setRuleEnabled = useMutation({
    mutationKey: latestConfigurationMutationKey,
    mutationFn: ({ ruleId, enabled }: { ruleId: string; enabled: boolean }) =>
      setLatestRuleEnabled(ruleId, enabled),
    onSuccess: refreshConfiguration,
  });
  const removeRule = useMutation({
    mutationKey: latestConfigurationMutationKey,
    mutationFn: deleteLatestRule,
    onSuccess: refreshConfiguration,
  });
  const preview = useMutation({
    mutationFn: ({ template, items }: LatestPreviewRequest) =>
      previewLatest(template, items),
  });
  const enrich = useMutation({
    mutationFn: enrichLatest,
    onSuccess: refreshSnapshot,
  });
  const clearState = useMutation({
    mutationFn: clearLatestState,
    onSuccess: refreshSnapshot,
  });
  const reset = useMutation({
    mutationFn: resetLatest,
    onSuccess: refreshSnapshot,
  });
  const resetScanTracking = useMutation({
    mutationFn: resetLatestScanTracking,
    onSuccess: refreshSnapshot,
  });

  useEffect(() => {
    if (!progressEnabled || !progress.data || progress.data.refreshing) return;
    setRefreshPending(false);
    refreshSnapshot();
  }, [progress.data, progressEnabled, refreshSnapshot]);

  return {
    snapshot,
    configuration,
    progress,
    isRefreshing: progressEnabled,
    workflowActive: latestOperations.workflowActive,
    configurationBusy,
    refresh,
    notify,
    workflow,
    preset,
    removePreset,
    rule,
    setRuleEnabled,
    removeRule,
    preview,
    enrich,
    clearState,
    reset,
    resetScanTracking,
    fetchLimits,
    refreshSnapshot,
    refreshConfiguration,
  };
}

export { useEmbyLatest };
