import { useCallback, useEffect, useRef, useState } from "react";

import { createStreamingSearch } from "@/features/research/api";
import type { SearchResult, StreamingSearchInput, StreamingSearchProgress } from "@/features/research/types";

type StreamingSearchState = {
  running: boolean;
  results: SearchResult[];
  progress: StreamingSearchProgress;
  error: string;
  warning: string;
  completedAt: string | null;
};

type SearchCancellationReason = "superseded" | "unmounted" | "cancelled";

type ActiveSearchRun = {
  generation: number;
  controller: AbortController;
  socket: WebSocket | null;
  settled: boolean;
  timedOut: boolean;
  cancellationReason: SearchCancellationReason | null;
  timeoutId?: number;
  onTimeout?: () => void;
  resolve?: () => void;
  reject?: (reason: Error) => void;
};

class StreamingSearchSupersededError extends Error {
  constructor() {
    super("Ricerca sostituita da un nuovo avvio");
    this.name = "StreamingSearchSupersededError";
  }
}

class StreamingSearchPartialError extends Error {
  readonly historySaved: boolean;

  constructor(message: string, historySaved = false) {
    super(message);
    this.name = "StreamingSearchPartialError";
    this.historySaved = historySaved;
  }
}

const initialState: StreamingSearchState = {
  running: false,
  results: [],
  progress: { completedQueries: 0 },
  error: "",
  warning: "",
  completedAt: null,
};

const streamingSearchClientTimeoutMs = 195_000;

function useStreamingSearch() {
  const generationRef = useRef(0);
  const activeRunRef = useRef<ActiveSearchRun | null>(null);
  const [state, setState] = useState<StreamingSearchState>(initialState);

  const dispose = useCallback(() => {
    generationRef.current += 1;
    const activeRun = activeRunRef.current;
    activeRunRef.current = null;
    cancelRun(activeRun, "unmounted");
  }, []);

  useEffect(() => dispose, [dispose]);

  const cancel = useCallback(() => {
    const activeRun = activeRunRef.current;
    if (!activeRun) return;
    generationRef.current += 1;
    activeRunRef.current = null;
    cancelRun(activeRun, "cancelled");
    setState((current) => ({ ...current, running: false, error: "", warning: "" }));
  }, []);

  const start = useCallback(async (input: StreamingSearchInput) => {
    cancelRun(activeRunRef.current, "superseded");
    const run: ActiveSearchRun = {
      generation: generationRef.current + 1,
      controller: new AbortController(),
      socket: null,
      settled: false,
      timedOut: false,
      cancellationReason: null,
    };
    generationRef.current = run.generation;
    activeRunRef.current = run;
    run.timeoutId = window.setTimeout(() => {
      run.timedOut = true;
      run.controller.abort();
      run.onTimeout?.();
    }, streamingSearchClientTimeoutMs);
    setState({ ...initialState, running: true });

    const isCurrentRun = () => activeRunRef.current === run && generationRef.current === run.generation;
    const isLatestGeneration = () => generationRef.current === run.generation;

    let session: Awaited<ReturnType<typeof createStreamingSearch>>;
    try {
      session = await createStreamingSearch(run.controller.signal);
    } catch (reason) {
      if (
        run.cancellationReason === "unmounted" ||
        run.cancellationReason === "cancelled"
      ) return;
      if (run.cancellationReason === "superseded" || !isCurrentRun()) {
        throw new StreamingSearchSupersededError();
      }
      const message = run.timedOut
        ? "La ricerca streaming ha superato il tempo massimo"
        : reason instanceof Error
          ? reason.message
          : "Impossibile preparare la ricerca streaming";
      run.settled = true;
      clearRunTimeout(run);
      activeRunRef.current = null;
      setState((current) => (
        isLatestGeneration() ? { ...current, running: false, error: message } : current
      ));
      throw new Error(message);
    }

    if (run.cancellationReason === "unmounted") return;
    if (run.cancellationReason === "superseded" || !isCurrentRun()) {
      throw new StreamingSearchSupersededError();
    }
    const websocketUrl = toWebSocketUrl(session.websocket_url);

    return new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(websocketUrl);
      run.socket = socket;
      run.resolve = resolve;
      run.reject = reject;

      function fail(message: string) {
        if (run.settled || !isCurrentRun()) return;
        run.settled = true;
        clearRunTimeout(run);
        activeRunRef.current = null;
        socket.close();
        setState((current) => (
          isLatestGeneration() ? { ...current, running: false, error: message } : current
        ));
        reject(new Error(message));
      }

      run.onTimeout = () => fail("La ricerca streaming ha superato il tempo massimo");

      socket.addEventListener("open", () => {
        if (run.settled || !isCurrentRun()) return;
        try {
          socket.send(JSON.stringify({
            action: "start_search",
            query_variants: [input.query],
            search_types: input.mediaType === "unknown" ? ["movie", "tv"] : [input.mediaType],
            indexers: input.indexers,
            use_jellyseerr_logic: false,
            use_custom_rules: Boolean(input.customRules),
            tmdb_id: input.tmdbId || "",
            custom_rules: input.customRules || null,
            seasons: input.seasons,
          }));
        } catch {
          fail("Impossibile avviare la ricerca sul WebSocket");
        }
      });

      socket.addEventListener("message", (event) => {
        if (run.settled || !isCurrentRun()) return;
        let message: Record<string, unknown>;
        try {
          message = JSON.parse(String(event.data)) as Record<string, unknown>;
        } catch {
          return;
        }
        const type = message.type;
        if (type === "result" && message.data && typeof message.data === "object") {
          setState((current) => (
            isLatestGeneration()
              ? { ...current, results: [...current.results, message.data as SearchResult] }
              : current
          ));
          return;
        }
        if (type === "query_completed") {
          setState((current) => (
            isLatestGeneration()
              ? {
                  ...current,
                  progress: {
                    completedQueries: current.progress.completedQueries + 1,
                    totalQueries: typeof message.total_queries === "number" ? message.total_queries : current.progress.totalQueries,
                    latestQuery: typeof message.query === "string" ? message.query : current.progress.latestQuery,
                    latestIndexer: typeof message.indexer === "string" ? message.indexer : current.progress.latestIndexer,
                  },
                }
              : current
          ));
          return;
        }
        if (type === "all_completed") {
          const terminalStatus = typeof message.status === "string" ? message.status : "success";
          const terminalMessage = typeof message.message === "string"
            ? message.message
            : "Ricerca streaming non riuscita";
          if (terminalStatus === "error") {
            fail(terminalMessage);
            return;
          }
          if (run.settled || !isCurrentRun()) return;
          run.settled = true;
          clearRunTimeout(run);
          activeRunRef.current = null;
          const filtered = Array.isArray(message.filtered_results) ? message.filtered_results as SearchResult[] : null;
          setState((current) => (
            isLatestGeneration()
              ? {
                  ...current,
                  running: false,
                  results: filtered || current.results,
                  progress: {
                    ...current.progress,
                    totalQueries: typeof message.total_queries === "number" ? message.total_queries : current.progress.totalQueries,
                  },
                  completedAt: typeof message.timestamp === "string" ? message.timestamp : new Date().toISOString(),
                  warning: terminalStatus === "partial" ? terminalMessage : "",
                }
              : current
          ));
          socket.close();
          if (terminalStatus === "partial") {
            reject(new StreamingSearchPartialError(
              terminalMessage,
              message.history_saved === true,
            ));
          } else {
            resolve();
          }
          return;
        }
        if (type === "error" && !message.query) {
          fail(typeof message.message === "string" ? message.message : "Errore durante la ricerca streaming");
        }
      });

      socket.addEventListener("error", () => fail("Connessione WebSocket per la ricerca non riuscita"));
      socket.addEventListener("close", () => {
        if (!run.settled) fail("Connessione WebSocket chiusa prima del completamento della ricerca");
      });
    });
  }, []);

  return { ...state, start, cancel };
}

function cancelRun(run: ActiveSearchRun | null, reason: SearchCancellationReason) {
  if (!run || run.settled) return;
  run.settled = true;
  clearRunTimeout(run);
  run.cancellationReason = reason;
  run.controller.abort();
  run.socket?.close();
  if (reason === "superseded") run.reject?.(new StreamingSearchSupersededError());
  else run.resolve?.();
}

function clearRunTimeout(run: ActiveSearchRun) {
  if (run.timeoutId !== undefined) {
    window.clearTimeout(run.timeoutId);
    run.timeoutId = undefined;
  }
}

function toWebSocketUrl(path: string) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return new URL(path, `${protocol}//${window.location.host}`).toString();
}

export {
  StreamingSearchPartialError,
  StreamingSearchSupersededError,
  streamingSearchClientTimeoutMs,
  useStreamingSearch,
};
