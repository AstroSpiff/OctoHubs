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

function libraryEventKind(
  event: ApplicationEvent,
): "configuration" | "library" | "scan" | null {
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
    let pendingKind: "configuration" | "library" | "scan" | null = null;
    const source = new EventSource("/api/emby/events-stream");

    source.onmessage = (message) => {
      if (document.visibilityState === "hidden") return;
      try {
        const kind = libraryEventKind(
          JSON.parse(message.data) as ApplicationEvent,
        );
        if (!kind) return;
        if (
          !pendingKind ||
          kind === "configuration" ||
          (kind === "library" && pendingKind === "scan")
        ) {
          pendingKind = kind;
        }
        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          timer = undefined;
          if (pendingKind === "configuration") {
            callbacksRef.current.onConfigurationChange();
          } else if (pendingKind === "library") {
            callbacksRef.current.onLibraryChange();
          } else if (pendingKind === "scan") {
            callbacksRef.current.onScanChange();
          }
          pendingKind = null;
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
    const clientId = `libraries-${crypto.randomUUID()}`;
    const subscriptions = jobIdsKey.split(",").filter(Boolean);

    const refresh = (completed: boolean) => {
      if (refreshTimer) window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        if (completed) callbacksRef.current.onLibraryChange();
        else callbacksRef.current.onScanChange();
      }, completed ? 0 : eventRefreshDelayMs);
    };

    const connect = () => {
      if (disposed || document.visibilityState === "hidden") return;
      socket = new WebSocket(scanSocketUrl(clientId));
      socket.addEventListener("open", () => {
        subscriptions.forEach((jobId) =>
          socket?.send(JSON.stringify({ action: "subscribe", job_id: jobId })),
        );
      });
      socket.addEventListener("message", (message) => {
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
      socket.addEventListener("close", () => {
        if (!disposed && document.visibilityState !== "hidden") {
          reconnectTimer = window.setTimeout(connect, reconnectDelayMs);
        }
      });
    };

    const handleVisibility = () => {
      if (document.visibilityState === "hidden") socket?.close();
      else if (!socket || socket.readyState === WebSocket.CLOSED) connect();
    };

    document.addEventListener("visibilitychange", handleVisibility);
    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (refreshTimer) window.clearTimeout(refreshTimer);
      document.removeEventListener("visibilitychange", handleVisibility);
      socket?.close();
    };
  }, [jobIdsKey]);
}

export { librariesUpdatedMessage, libraryEventKind, useLibrariesRealtime };
