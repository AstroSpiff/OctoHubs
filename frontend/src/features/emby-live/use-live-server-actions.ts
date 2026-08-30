import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import type { ConfirmationOptions } from "@/components/ui/confirmation-dialog";
import {
  restartEmbyServers,
  stopEmbyTask,
} from "@/features/emby-live/server-actions-api";
import { embyTaskActionKey } from "@/features/emby-live/task-action";

type LiveServerActionsOptions = {
  confirm: (options: ConfirmationOptions) => Promise<boolean>;
  refreshLive: () => void;
  refreshServer: (serverId: string) => Promise<void>;
};

function useLiveServerActions({
  confirm,
  refreshLive,
  refreshServer,
}: LiveServerActionsOptions) {
  const [refreshingServerIds, setRefreshingServerIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [refreshErrors, setRefreshErrors] = useState<Record<string, string>>({});
  const [stoppingTaskKeys, setStoppingTaskKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const [taskStopErrors, setTaskStopErrors] = useState<Record<string, string>>({});
  const [taskNotice, setTaskNotice] = useState<string | null>(null);
  const restart = useMutation({
    mutationFn: restartEmbyServers,
    onSuccess: refreshLive,
  });
  const stopTask = useMutation({
    mutationFn: ({ serverId, taskId }: { serverId: string; taskId: string }) =>
      stopEmbyTask(serverId, taskId),
    onSuccess: refreshLive,
  });

  async function requestRestart(serverId?: string) {
    const target = serverId
      ? "questo server Emby"
      : "tutti i server Emby abilitati";
    if (!(await confirm({
      title: "Riavvia server Emby",
      description: `Vuoi riavviare ${target}? Le riproduzioni in corso potrebbero interrompersi.`,
      confirmLabel: "Riavvia",
      tone: "danger",
    }))) return;

    setTaskNotice(null);
    restart.reset();
    restart.mutate(serverId);
  }

  async function requestRefresh(serverId: string) {
    setRefreshingServerIds((current) => new Set(current).add(serverId));
    setRefreshErrors((current) => {
      if (!(serverId in current)) return current;
      const next = { ...current };
      delete next[serverId];
      return next;
    });

    try {
      await refreshServer(serverId);
    } catch (reason) {
      setRefreshErrors((current) => ({
        ...current,
        [serverId]: reason instanceof Error
          ? reason.message
          : "Errore aggiornamento informazioni server.",
      }));
    } finally {
      setRefreshingServerIds((current) => {
        const next = new Set(current);
        next.delete(serverId);
        return next;
      });
    }
  }

  async function requestStopTask(
    serverId: string,
    taskId: string,
    taskName?: string,
  ) {
    if (!(await confirm({
      title: "Ferma operazione Emby",
      description: `Vuoi fermare ${taskName || "questa operazione"}? Emby potrebbe lasciare incompleto il lavoro in corso.`,
      confirmLabel: "Ferma operazione",
      tone: "danger",
    }))) return;

    const taskKey = embyTaskActionKey(serverId, taskId);
    setStoppingTaskKeys((current) => new Set(current).add(taskKey));
    setTaskStopErrors((current) => {
      if (!(taskKey in current)) return current;
      const next = { ...current };
      delete next[taskKey];
      return next;
    });
    setTaskNotice(null);

    try {
      const result = await stopTask.mutateAsync({ serverId, taskId });
      setTaskNotice(result.message || "Richiesta di arresto inviata a Emby.");
    } catch (reason) {
      setTaskStopErrors((current) => ({
        ...current,
        [taskKey]: reason instanceof Error
          ? reason.message
          : "Impossibile fermare questa operazione Emby.",
      }));
    } finally {
      setStoppingTaskKeys((current) => {
        const next = new Set(current);
        next.delete(taskKey);
        return next;
      });
    }
  }

  return {
    refreshErrors,
    refreshingServerIds,
    requestRefresh,
    requestRestart,
    requestStopTask,
    restart,
    stoppingTaskKeys,
    taskNotice,
    taskStopErrors,
  };
}

export { useLiveServerActions };
