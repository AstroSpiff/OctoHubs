import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { checkTranscodeGuard, cleanupGuardEvents, cleanupGuardStreams, getTranscodeGuardStatus, setTranscodeGuardState } from "@/features/transcode-guard/api";
import { isEventBridgeUpdate } from "@/lib/application-events";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

export function useTranscodeGuard() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["transcode-guard-status"],
    queryFn: getTranscodeGuardStatus,
    refetchInterval: 5_000,
  });
  const refreshStatus = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["transcode-guard-status"] });
  }, [queryClient]);
  useApplicationEventRefresh(isEventBridgeUpdate, refreshStatus);
  const checkNow = useMutation({
    mutationFn: checkTranscodeGuard,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["transcode-guard-status"] }),
  });
  const setState = useMutation({
    mutationFn: setTranscodeGuardState,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["transcode-guard-status"] });
      await queryClient.invalidateQueries({ queryKey: ["transcode-guard-settings"] });
    },
  });
  const cleanupEvents = useMutation({
    mutationFn: cleanupGuardEvents,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["transcode-guard-status"] }),
  });
  const cleanupStreams = useMutation({
    mutationFn: cleanupGuardStreams,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["transcode-guard-status"] }),
  });

  return { status, checkNow, setState, cleanupEvents, cleanupStreams };
}
