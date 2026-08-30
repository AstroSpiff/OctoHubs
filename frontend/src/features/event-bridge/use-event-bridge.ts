import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getEventBridgeStatus, provisionEventBridgeCredential, saveEventBridgeSettings } from "@/features/event-bridge/api";
import { eventBridgeSaveNotice, eventBridgeSettingsEqual } from "@/features/event-bridge/presentation";
import type { EventBridgeSettings } from "@/features/event-bridge/types";
import type { EventBridgeSaveNotice } from "@/features/event-bridge/presentation";
import { useEventBridgeRealtime } from "@/features/event-bridge/use-event-bridge-realtime";

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
  const save = useMutation({
    mutationFn: ({ serverId, settings }: { serverId: string; settings: EventBridgeSettings }) => saveEventBridgeSettings(serverId, settings),
    onSuccess: async (result, variables) => {
      setNotice(eventBridgeSaveNotice(result));
      const currentDraft = draftsRef.current[variables.serverId];
      if (!currentDraft || eventBridgeSettingsEqual(currentDraft, variables.settings)) {
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
    mutationFn: provisionEventBridgeCredential,
    onSuccess: async (result) => {
      setNotice({ message: result.message, tone: "success" });
      await queryClient.invalidateQueries({ queryKey: ["event-bridge-status"] });
    },
  });

  useEffect(() => {
    const servers = status.data?.servers || [];
    setDrafts((current) => {
      const next = { ...current };
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

  return { status, drafts, dirtyIds, notice, save, provision, servers, updateDraft };
}
