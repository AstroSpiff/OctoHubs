import { useCallback, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getActiveLibraryScans,
  getActiveScanJobs,
  getGroupedLibraries,
  getLibraryActionTargets,
  getLibraryAssociations,
  getLibraryScanHistory,
  deleteLibraryScanHistoryJob,
  resetLibraryScanHistory,
  runLibraryMaintenance,
  saveEmbyServerOrder,
  saveLibraryAssociations,
  saveLibraryGroupOrder,
  scanLibraryGroup,
  scanSingleLibrary,
  startLibraryWorkflow,
} from "@/features/libraries/api";
import { useLibrariesRealtime } from "@/features/libraries/use-libraries-realtime";
import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";

function libraryOperationKey(library: { server_id: string; library_id?: string; id?: string }) {
  return `${library.server_id}:${library.library_id || library.id || ""}`;
}

function workflowOperationKeys(context: Parameters<typeof startLibraryWorkflow>[0]) {
  if (context.library_id && context.server_id) {
    return {
      groups: [] as string[],
      libraries: [`${context.server_id}:${context.library_id}`],
      maintenance: [] as string[],
    };
  }
  return {
    groups: context.group_name ? [context.group_name] : [],
    libraries: [] as string[],
    maintenance: context.group_name
      ? []
      : [context.server_id ? `workflow:server:${context.server_id}` : "workflow:all"],
  };
}

function useLibraries() {
  const client = useQueryClient();
  const groupScanOperations = useKeyedOperationState();
  const libraryScanOperations = useKeyedOperationState();
  const workflowMaintenanceOperations = useKeyedOperationState();
  const historyDeleteOperations = useKeyedOperationState();
  const groups = useQuery({
    queryKey: ["library-groups"],
    queryFn: getGroupedLibraries,
    refetchInterval: 15_000,
  });
  const activeJobs = useQuery({
    queryKey: ["library-scan-jobs"],
    queryFn: getActiveScanJobs,
    refetchInterval: 3_000,
  });
  const activeScans = useQuery({
    queryKey: ["library-active-scans"],
    queryFn: getActiveLibraryScans,
    refetchInterval: 5_000,
  });
  const history = useQuery({
    queryKey: ["library-scan-history"],
    queryFn: getLibraryScanHistory,
    refetchInterval: 30_000,
  });
  const associations = useQuery({
    queryKey: ["library-associations"],
    queryFn: getLibraryAssociations,
  });
  const actionTargets = useQuery({
    queryKey: ["library-action-targets"],
    queryFn: getLibraryActionTargets,
  });
  const refresh = useCallback(() =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["library-groups"] }),
      client.invalidateQueries({ queryKey: ["library-scan-jobs"] }),
      client.invalidateQueries({ queryKey: ["library-active-scans"] }),
      client.invalidateQueries({ queryKey: ["library-scan-history"] }),
      client.invalidateQueries({ queryKey: ["library-associations"] }),
      client.invalidateQueries({ queryKey: ["library-action-targets"] }),
    ]), [client]);
  const refreshScanState = useCallback(() => {
    void Promise.all([
      client.invalidateQueries({ queryKey: ["library-scan-jobs"] }),
      client.invalidateQueries({ queryKey: ["library-active-scans"] }),
    ]);
  }, [client]);
  const refreshLibraryState = useCallback(() => {
    void Promise.all([
      client.invalidateQueries({ queryKey: ["library-groups"] }),
      client.invalidateQueries({ queryKey: ["library-scan-jobs"] }),
      client.invalidateQueries({ queryKey: ["library-active-scans"] }),
      client.invalidateQueries({ queryKey: ["library-scan-history"] }),
    ]);
  }, [client]);
  const refreshLibraryConfiguration = useCallback(() => {
    void Promise.all([
      client.invalidateQueries({ queryKey: ["library-groups"] }),
      client.invalidateQueries({ queryKey: ["library-associations"] }),
      client.invalidateQueries({ queryKey: ["library-action-targets"] }),
    ]);
  }, [client]);
  const activeJobsData = useMemo(() => activeJobs.data?.jobs || [], [activeJobs.data]);
  useLibrariesRealtime(activeJobsData, {
    onConfigurationChange: refreshLibraryConfiguration,
    onScanChange: refreshScanState,
    onLibraryChange: refreshLibraryState,
  });
  const scan = useMutation({
    mutationFn: ({
      group,
      scanType,
    }: Parameters<typeof scanLibraryGroup>[0] extends never
      ? never
      : {
          group: Parameters<typeof scanLibraryGroup>[0];
          scanType: Parameters<typeof scanLibraryGroup>[1];
    }) => scanLibraryGroup(group, scanType),
    onMutate: ({ group }) => groupScanOperations.begin([group.group_name]),
    onError: (error, { group }) => groupScanOperations.fail([group.group_name], error),
    onSettled: (_data, _error, { group }) => groupScanOperations.finish([group.group_name]),
    onSuccess: refresh,
  });
  const libraryScan = useMutation({
    mutationFn: ({
      library,
      scanType,
    }: {
      library: Parameters<typeof scanSingleLibrary>[0];
      scanType: Parameters<typeof scanSingleLibrary>[1];
    }) => scanSingleLibrary(library, scanType),
    onMutate: ({ library }) => libraryScanOperations.begin([libraryOperationKey(library)]),
    onError: (error, { library }) => libraryScanOperations.fail([libraryOperationKey(library)], error),
    onSettled: (_data, _error, { library }) => libraryScanOperations.finish([libraryOperationKey(library)]),
    onSuccess: refresh,
  });
  const saveAssociations = useMutation({
    mutationFn: saveLibraryAssociations,
    onSuccess: refresh,
  });
  const saveGroupOrder = useMutation({
    mutationFn: saveLibraryGroupOrder,
    onSuccess: refresh,
  });
  const saveServerOrder = useMutation({
    mutationFn: saveEmbyServerOrder,
    onSuccess: refresh,
  });
  const action = useMutation({
    mutationFn: runLibraryMaintenance,
    onSuccess: refresh,
  });
  const resetHistory = useMutation({
    mutationFn: resetLibraryScanHistory,
    onSuccess: refresh,
  });
  const deleteHistoryJob = useMutation({
    mutationFn: deleteLibraryScanHistoryJob,
    onMutate: (jobId) => historyDeleteOperations.begin([jobId]),
    onError: (error, jobId) => historyDeleteOperations.fail([jobId], error),
    onSettled: (_data, _error, jobId) => historyDeleteOperations.finish([jobId]),
    onSuccess: refresh,
  });
  const workflow = useMutation({
    mutationFn: startLibraryWorkflow,
    onMutate: (context) => {
      const keys = workflowOperationKeys(context);
      groupScanOperations.begin(keys.groups);
      libraryScanOperations.begin(keys.libraries);
      workflowMaintenanceOperations.begin(keys.maintenance);
    },
    onError: (error, context) => {
      const keys = workflowOperationKeys(context);
      groupScanOperations.fail(keys.groups, error);
      libraryScanOperations.fail(keys.libraries, error);
      workflowMaintenanceOperations.fail(keys.maintenance, error);
    },
    onSettled: (_data, _error, context) => {
      const keys = workflowOperationKeys(context);
      groupScanOperations.finish(keys.groups);
      libraryScanOperations.finish(keys.libraries);
      workflowMaintenanceOperations.finish(keys.maintenance);
    },
    onSuccess: refresh,
  });

  return {
    groups,
    activeJobs,
    activeScans,
    history,
    associations,
    actionTargets,
    scan,
    libraryScan,
    saveAssociations,
    saveGroupOrder,
    saveServerOrder,
    action,
    resetHistory,
    deleteHistoryJob,
    workflow,
    groupScanOperations,
    libraryScanOperations,
    workflowMaintenanceOperations,
    historyDeleteOperations,
    refresh,
  };
}

export { useLibraries };
