import { useEffect, useRef } from "react";

import type { ScanJob } from "@/features/libraries/types";
import { configurationUpdateScope } from "@/lib/application-events";
import type { ApplicationEvent } from "@/lib/use-application-event";

const eventRefreshDelayMs = 350;
const reconnectDelayMs = 2_000;
const librariesUpdatedMessage = "OctoHubsLibrariesUpdated";

type ScanSocketMessage = {
  type?: unknown;
};

type LibrariesRealtimeCallbacks = {
  onConfigurationChange: () => void;
  onLibraryChange: () => void;
  onScanChange: () => void;
};

type LibraryEventKind = "configuration" | "library" | "scan";

function flushLibraryEventKinds(
  kinds: ReadonlySet<LibraryEventKind>,
  callbacks: LibrariesRealtimeCallbacks,
) {
  if (kinds.has("configuration")) callbacks.onConfigurationChange();
  if (kinds.has("library")) callbacks.onLibraryChange();
  if (kinds.has("scan")) callbacks.onScanChange();
}

function libraryEventKind(
  event: ApplicationEvent,
): LibraryEventKind | null {
  const messageType = String(event.MessageType || "");
  if (messageType === "RefreshProgress") return "scan";
  if (messageType === librariesUpdatedMessage) {
    const data = event.Data;
    const scope =
      data && typeof data === "object"
        ? String((data as { scope?: unknown }).scope || "")
        : "";
    return scope === "history" || scope === "scan"
      ? "library"
      : "configuration";
  }
  if (configurationUpdateScope(event) === "servers") return "configuration";
  if (
    [
      "LibraryChanged",
      "ScheduledTasksInfo",
      "ScheduledTasksInfoStart",
      "ScheduledTasksInfoStop",
    ].includes(messageType)
  )
    return "library";
  return null;
}

function scanSocketUrl(clientId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return new URL(
    `/ws/scan/${encodeURIComponent(clientId)}`,
    `${protocol}//${window.location.host}`,
  ).toString();
}

function useLibrariesRealtime(
  jobs: ScanJob[],
  { onConfigurationChange, onLibraryChange, onScanChange }: LibrariesRealtimeCallbacks,
) {
  const callbacksRef = useRef({
    onConfigurationChange,
    onLibraryChange,
    onScanChange,
  });
  const jobIdsKey = jobs
    .map((job) => job.job_id)
    .sort()
    .join(",");

  useEffect(() => {
    callbacksRef.current = {
      onConfigurationChange,
      onLibraryChange,
      onScanChange,
    };
  }, [onConfigurationChange, onLibraryChange, onScanChange]);

  useEffect(() => {
    let timer: number | undefined;
    const pendingKinds = new Set<LibraryEventKind>();
    const source = new EventSource("/api/emby/events-stream");

    source.onmessage = (message) => {
      if (document.visibilityState === "hidden") return;
      try {
        const kind = libraryEventKind(
          JSON.parse(message.data) as ApplicationEvent,
        );
        if (!kind) return;
        pendingKinds.add(kind);
        if (timer) return;
        timer = window.setTimeout(() => {
          timer = undefined;
          flushLibraryEventKinds(pendingKinds, callbacksRef.current);
          pendingKinds.clear();
        }, eventRefreshDelayMs);
      } catch {
        // React Query polling remains the fallback for malformed events.
      }
    };

    return () => {
      if (timer) window.clearTimeout(timer);
      source.close();
    };
  }, []);

  useEffect(() => {
    if (!jobIdsKey) return;

    let disposed = false;
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;
    let refreshTimer: number | undefined;
    let socketGeneration = 0;
    const clientId = `libraries-${crypto.randomUUID()}`;
    const subscriptions = jobIdsKey.split(",").filter(Boolean);

    const refresh = (completed: boolean) => {
      if (completed && refreshTimer) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      } else if (refreshTimer) {
        return;
      }
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        if (completed) callbacksRef.current.onLibraryChange();
        else callbacksRef.current.onScanChange();
      }, completed ? 0 : eventRefreshDelayMs);
    };

    const cancelReconnect = () => {
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
      }
    };

    const connect = () => {
      if (disposed || document.visibilityState === "hidden") return;
      cancelReconnect();
      const generation = ++socketGeneration;
      const currentSocket = new WebSocket(scanSocketUrl(clientId));
      socket = currentSocket;
      currentSocket.addEventListener("open", () => {
        if (disposed || generation !== socketGeneration || socket !== currentSocket)
          return;
        subscriptions.forEach((jobId) =>
          currentSocket.send(
            JSON.stringify({ action: "subscribe", job_id: jobId }),
          ),
        );
      });
      currentSocket.addEventListener("message", (message) => {
        if (disposed || generation !== socketGeneration || socket !== currentSocket)
          return;
        try {
          const type = String(
            (JSON.parse(message.data) as ScanSocketMessage).type || "",
          );
          if (type === "progress") refresh(false);
          if (type === "completed" || type === "error") refresh(true);
        } catch {
          // Polling covers a bad WebSocket payload without disrupting the page.
        }
      });
      currentSocket.addEventListener("close", () => {
        if (generation !== socketGeneration || socket !== currentSocket) return;
        socket = undefined;
        if (disposed || document.visibilityState === "hidden") return;
        cancelReconnect();
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = undefined;
          connect();
        }, reconnectDelayMs);
      });
    };

    const handleVisibility = () => {
      if (document.visibilityState === "hidden") {
        cancelReconnect();
        socket?.close();
      } else if (!socket || socket.readyState === WebSocket.CLOSED) {
        connect();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    connect();

    return () => {
      disposed = true;
      cancelReconnect();
      if (refreshTimer) window.clearTimeout(refreshTimer);
      document.removeEventListener("visibilitychange", handleVisibility);
      socketGeneration += 1;
      const activeSocket = socket;
      socket = undefined;
      activeSocket?.close();
    };
  }, [jobIdsKey]);
}

export {
  flushLibraryEventKinds,
  librariesUpdatedMessage,
  libraryEventKind,
  useLibrariesRealtime,
};
