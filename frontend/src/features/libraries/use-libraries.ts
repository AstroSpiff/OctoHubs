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

function useLibraries() {
  const client = useQueryClient();
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
    onSuccess: refresh,
  });
  const workflow = useMutation({
    mutationFn: startLibraryWorkflow,
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
    refresh,
  };
}

export { useLibraries };
