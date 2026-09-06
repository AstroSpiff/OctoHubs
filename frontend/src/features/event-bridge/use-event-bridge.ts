import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getEventBridgeStatus, provisionEventBridgeCredential, saveEventBridgeSettings } from "@/features/event-bridge/api";
import { eventBridgeSaveNotice, eventBridgeSettingsEqual } from "@/features/event-bridge/presentation";
import type { EventBridgeSettings, EventBridgeStatus } from "@/features/event-bridge/types";
import type { EventBridgeSaveNotice } from "@/features/event-bridge/presentation";
import { useEventBridgeRealtime } from "@/features/event-bridge/use-event-bridge-realtime";
import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";

export function useEventBridge() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["event-bridge-status"],
    queryFn: getEventBridgeStatus,
    refetchInterval: 15_000,
  });
  const refreshStatus = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["event-bridge-status"] });
  }, [queryClient]);
  useEventBridgeRealtime(refreshStatus);
  const [drafts, setDrafts] = useState<Record<string, EventBridgeSettings>>({});
  const draftsRef = useRef<Record<string, EventBridgeSettings>>({});
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<EventBridgeSaveNotice | null>(null);
  const provisionOperations = useKeyedOperationState();
  const provisioningRef = useRef(new Set<string>());
  const save = useMutation({
    mutationFn: ({ serverId, settings }: { serverId: string; settings: EventBridgeSettings }) => saveEventBridgeSettings(serverId, settings),
    onSuccess: async (result, variables) => {
      setNotice(eventBridgeSaveNotice(result));
      const currentDraft = draftsRef.current[variables.serverId];
      if (!currentDraft || eventBridgeSettingsEqual(currentDraft, variables.settings)) {
        queryClient.setQueryData<EventBridgeStatus>(["event-bridge-status"], (current) => {
          if (!current) return current;
          return {
            ...current,
            servers: current.servers.map((server) =>
              server.id === variables.serverId
                ? { ...server, settings: variables.settings }
                : server,
            ),
          };
        });
        setDrafts((current) => {
          const next = { ...current, [variables.serverId]: variables.settings };
          draftsRef.current = next;
          return next;
        });
        setDirtyIds((current) => {
          const next = new Set(current);
          next.delete(variables.serverId);
          return next;
        });
      }
      await queryClient.invalidateQueries({ queryKey: ["event-bridge-status"] });
    },
  });
  const provision = useMutation({
    mutationFn: async (serverId: string) => {
      if (provisioningRef.current.has(serverId))
        throw new Error("Collegamento Event Bridge già in corso per questo server");
      provisioningRef.current.add(serverId);
      try {
        return await provisionEventBridgeCredential(serverId);
      } finally {
        provisioningRef.current.delete(serverId);
      }
    },
    onMutate: (serverId) => provisionOperations.begin([serverId]),
    onError: (error, serverId) => provisionOperations.fail([serverId], error),
    onSuccess: async (result) => {
      provisionOperations.clear([result.server_id]);
      setNotice({ message: result.message, tone: "success" });
      await queryClient.invalidateQueries({ queryKey: ["event-bridge-status"] });
    },
    onSettled: (_data, _error, serverId) =>
      provisionOperations.finish([serverId]),
  });

  useEffect(() => {
    const servers = status.data?.servers || [];
    const currentIds = new Set(servers.map((server) => server.id));
    setDirtyIds((current) => {
      const next = new Set([...current].filter((serverId) => currentIds.has(serverId)));
      return next.size === current.size ? current : next;
    });
    setDrafts((current) => {
      const next = Object.fromEntries(
        Object.entries(current).filter(([serverId]) => currentIds.has(serverId)),
      );
      servers.forEach((server) => {
        if (!dirtyIds.has(server.id)) next[server.id] = server.settings;
      });
      draftsRef.current = next;
      return next;
    });
  }, [dirtyIds, status.data?.servers]);

  const servers = useMemo(
    () => [...(status.data?.servers || [])].sort((left, right) => left.name.localeCompare(right.name, "it")),
    [status.data?.servers],
  );

  function updateDraft(serverId: string, settings: EventBridgeSettings) {
    setDrafts((current) => {
      const next = { ...current, [serverId]: settings };
      draftsRef.current = next;
      return next;
    });
    const savedSettings = status.data?.servers.find((server) => server.id === serverId)?.settings;
    setDirtyIds((current) => {
      const next = new Set(current);
      if (savedSettings && eventBridgeSettingsEqual(settings, savedSettings)) next.delete(serverId);
      else next.add(serverId);
      return next;
    });
  }

  return {
    status,
    drafts,
    dirtyIds,
    notice,
    save,
    provision,
    provisionOperations,
    servers,
    updateDraft,
  };
}
