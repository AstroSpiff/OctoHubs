import { useCallback, useEffect, useRef, useState } from "react";

import { getEmbyLiveSnapshot, getEmbyServerStatus } from "@/features/emby-live/api";
import { liveConnectionFromHeartbeat } from "@/features/emby-live/live-connection";
import type {
  EmbyLiveSnapshot,
  LiveConnectionState,
} from "@/features/emby-live/types";

const staleAfterMilliseconds = 8_000;
const fallbackPollIntervalMilliseconds = 5_000;
const fallbackStaleAfterMilliseconds = 11_000;

function useEmbyLive() {
  const [snapshot, setSnapshot] = useState<EmbyLiveSnapshot | null>(null);
  const [connection, setConnection] = useState<LiveConnectionState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState(0);
  const [generation, setGeneration] = useState(0);
  const snapshotRevisionRef = useRef(0);
  const serverRefreshGenerationRef = useRef(new Map<string, number>());

  const refresh = useCallback(() => {
    // Any per-server response started before the full refresh is stale.
    snapshotRevisionRef.current += 1;
    setConnection("loading");
    setError(null);
    setGeneration((value) => value + 1);
  }, []);
  const refreshServer = useCallback(async (serverId: string) => {
    const revision = snapshotRevisionRef.current;
    const serverGeneration = (serverRefreshGenerationRef.current.get(serverId) || 0) + 1;
    serverRefreshGenerationRef.current.set(serverId, serverGeneration);
    const status = await getEmbyServerStatus(serverId);
    if (
      revision !== snapshotRevisionRef.current ||
      serverRefreshGenerationRef.current.get(serverId) !== serverGeneration
    ) return;
    setSnapshot((current) => {
      const server = current?.servers[serverId];
      if (!current || !server) return current;
      return {
        ...current,
        servers: {
          ...current.servers,
          [serverId]: { ...server, ...status },
        },
      };
    });
    setUpdatedAt(Date.now());
  }, []);

  useEffect(() => {
    let disposed = false;
    let lastSsePayloadAt = 0;
    let lastFallbackAt = 0;
    let lastFallbackRequestAt = 0;
    let fallbackRequestActive = false;
    let fallbackController: AbortController | null = null;
    const connectedAt = Date.now();
    const connectionState = () => liveConnectionFromHeartbeat({
      connectedAt,
      lastPayloadAt: lastSsePayloadAt,
      lastFallbackAt,
      now: Date.now(),
      staleAfterMilliseconds,
      fallbackStaleAfterMilliseconds,
    });
    const refreshConnectionState = () => {
      if (!disposed) setConnection(connectionState());
    };
    const requestFallback = async (force = false) => {
      if (disposed) return;
      const now = Date.now();
      if (
        fallbackRequestActive ||
        (!force && now - (lastSsePayloadAt || connectedAt) <= staleAfterMilliseconds) ||
        now - lastFallbackRequestAt < fallbackPollIntervalMilliseconds
      ) return;

      fallbackRequestActive = true;
      lastFallbackRequestAt = now;
      const controller = new AbortController();
      fallbackController = controller;
      try {
        const payload = await getEmbyLiveSnapshot(controller.signal);
        if (disposed || controller.signal.aborted || fallbackController !== controller) return;
        if (!payload.success) throw new Error("Impossibile aggiornare lo stato Emby.");
        lastFallbackAt = Date.now();
        snapshotRevisionRef.current += 1;
        setSnapshot(payload);
        setUpdatedAt(lastFallbackAt);
        setError(null);
      } catch (reason) {
        if (disposed || controller.signal.aborted || fallbackController !== controller) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "Aggiornamento periodico Emby non riuscito.",
        );
      } finally {
        if (fallbackController === controller) {
          fallbackController = null;
          fallbackRequestActive = false;
          refreshConnectionState();
        }
      }
    };
    const source = typeof EventSource === "undefined"
      ? null
      : new EventSource("/api/emby/status-stream");
    const watchdog = window.setInterval(() => {
      refreshConnectionState();
      void requestFallback();
    }, 2_000);

    if (source) {
      source.onopen = () => {
        if (disposed) return;
        if (!lastSsePayloadAt) setConnection("loading");
      };
      source.onmessage = (event) => {
        if (disposed) return;
        try {
          const payload = JSON.parse(event.data) as EmbyLiveSnapshot & {
            message?: string;
          };
          if (!payload.success)
            throw new Error(
              payload.message || "Impossibile aggiornare lo stato Emby.",
            );
          fallbackController?.abort();
          lastSsePayloadAt = Date.now();
          snapshotRevisionRef.current += 1;
          setSnapshot(payload);
          setUpdatedAt(lastSsePayloadAt);
          setError(null);
          setConnection("connected");
        } catch (reason) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Risposta Emby non valida.",
          );
        }
      };
      source.onerror = () => {
        if (disposed) return;
        setConnection("reconnecting");
        void requestFallback(true);
      };
    } else {
      void requestFallback(true);
    }

    return () => {
      disposed = true;
      fallbackController?.abort();
      window.clearInterval(watchdog);
      source?.close();
    };
  }, [generation]);

  return { snapshot, connection, error, updatedAt, refresh, refreshServer };
}

export { useEmbyLive };
