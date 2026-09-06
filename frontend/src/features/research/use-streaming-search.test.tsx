// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createStreamingSearch } from "@/features/research/api";
import { SearchResultTable } from "@/features/research/components/search-result-table";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import {
  streamingSearchClientTimeoutMs,
  useStreamingSearch,
} from "@/features/research/use-streaming-search";

vi.mock("@/features/research/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/research/api")>()),
  createStreamingSearch: vi.fn(),
}));

let latest: ReturnType<typeof useStreamingSearch> | undefined;

type SocketListener = (event: { data?: unknown }) => void;

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readonly sent: string[] = [];
  closed = false;
  private readonly listeners = new Map<string, SocketListener[]>();

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: SocketListener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, event: { data?: unknown } = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event);
  }
}

const alienSearch = {
  query: "Alien",
  mediaType: "movie" as const,
  indexers: ["prowlarr" as const],
  seasons: [],
};

const bladeRunnerSearch = {
  query: "Blade Runner",
  mediaType: "movie" as const,
  indexers: ["jackett" as const],
  seasons: [],
};

function Harness() {
  latest = useStreamingSearch();
  return null;
}

function StreamingTableHarness() {
  latest = useStreamingSearch();
  return (
    <WorkspaceCapabilitiesProvider canMutate>
      <SearchResultTable
        results={latest.results}
        qbittorrentAvailable={false}
        resultSetId={1}
      />
    </WorkspaceCapabilitiesProvider>
  );
}

describe("useStreamingSearch", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    latest = undefined;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<Harness />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it("marks the search as running before the WebSocket session is ready", async () => {
    let rejectSession: (reason?: unknown) => void = () => undefined;
    vi.mocked(createStreamingSearch).mockImplementation(
      () => new Promise((_resolve, reject) => { rejectSession = reject; }),
    );
    let pending: Promise<void> | undefined;

    act(() => {
      pending = latest?.start({
        ...alienSearch,
      });
    });

    expect(latest?.running).toBe(true);

    await act(async () => {
      rejectSession(new Error("Sessione non disponibile"));
      await expect(pending).rejects.toThrow("Sessione non disponibile");
    });

    expect(latest?.running).toBe(false);
    expect(latest?.error).toBe("Sessione non disponibile");
  });

  it("ignores a session response from a superseded start", async () => {
    const sessions: Array<{
      signal: AbortSignal | undefined;
      resolve: (value: { success: boolean; session_id: string; websocket_url: string }) => void;
    }> = [];
    vi.mocked(createStreamingSearch).mockImplementation((signal) => new Promise((resolve) => {
      sessions.push({ signal, resolve });
    }));

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = latest!.start(alienSearch);
    });
    const firstWasSuperseded = first.then(
      () => false,
      (reason: unknown) => reason instanceof Error && reason.message.includes("sostituita"),
    );
    act(() => {
      second = latest!.start(bladeRunnerSearch);
    });

    expect(sessions).toHaveLength(2);
    expect(sessions[0].signal?.aborted).toBe(true);

    await act(async () => {
      sessions[1].resolve({ success: true, session_id: "second", websocket_url: "/ws/search/second" });
      await Promise.resolve();
    });

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("/ws/search/second");

    await act(async () => {
      sessions[0].resolve({ success: true, session_id: "first", websocket_url: "/ws/search/first" });
      await Promise.resolve();
    });

    await expect(firstWasSuperseded).resolves.toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(1);

    const activeSocket = FakeWebSocket.instances[0];
    act(() => {
      activeSocket.emit("open");
      activeSocket.emit("message", {
        data: JSON.stringify({ type: "result", data: { title: "Blade Runner result" } }),
      });
      activeSocket.emit("message", {
        data: JSON.stringify({
          type: "all_completed",
          filtered_results: [{ title: "Blade Runner result" }],
          timestamp: "2026-08-29T20:00:00Z",
        }),
      });
    });
    await act(async () => second);

    expect(latest?.results.map((result) => result.title)).toEqual(["Blade Runner result"]);
    expect(latest?.error).toBe("");
    expect(latest?.running).toBe(false);
  });

  it("ignores messages and close events from a replaced socket", async () => {
    vi.mocked(createStreamingSearch)
      .mockResolvedValueOnce({ success: true, session_id: "first", websocket_url: "/ws/search/first" })
      .mockResolvedValueOnce({ success: true, session_id: "second", websocket_url: "/ws/search/second" });

    let first!: Promise<void>;
    await act(async () => {
      first = latest!.start(alienSearch);
      await Promise.resolve();
    });
    const firstWasSuperseded = first.then(
      () => false,
      (reason: unknown) => reason instanceof Error && reason.message.includes("sostituita"),
    );
    const firstSocket = FakeWebSocket.instances[0];

    let second!: Promise<void>;
    await act(async () => {
      second = latest!.start(bladeRunnerSearch);
      await Promise.resolve();
    });
    const secondSocket = FakeWebSocket.instances[1];

    expect(firstSocket.closed).toBe(true);
    await expect(firstWasSuperseded).resolves.toBe(true);

    act(() => {
      firstSocket.emit("message", {
        data: JSON.stringify({ type: "result", data: { title: "Stale Alien result" } }),
      });
      firstSocket.emit("close");
      secondSocket.emit("message", {
        data: JSON.stringify({ type: "result", data: { title: "Current result" } }),
      });
      secondSocket.emit("message", {
        data: JSON.stringify({
          type: "all_completed",
          filtered_results: [{ title: "Current result" }],
        }),
      });
    });
    await act(async () => second);

    expect(latest?.results.map((result) => result.title)).toEqual(["Current result"]);
    expect(latest?.error).toBe("");
  });

  it("terminates an open socket that never sends a terminal frame", async () => {
    vi.useFakeTimers();
    vi.mocked(createStreamingSearch).mockResolvedValue({
      success: true,
      session_id: "timeout",
      websocket_url: "/ws/search/timeout",
    });
    let run!: Promise<void>;
    await act(async () => {
      run = latest!.start(alienSearch);
      await Promise.resolve();
    });
    const timedOut = expect(run).rejects.toThrow("tempo massimo");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(streamingSearchClientTimeoutMs);
    });

    await timedOut;
    expect(FakeWebSocket.instances[0].closed).toBe(true);
    expect(latest?.running).toBe(false);
    vi.useRealTimers();
  });

  it("applies the same deadline while the streaming session request is pending", async () => {
    vi.useFakeTimers();
    vi.mocked(createStreamingSearch).mockImplementation((signal) => new Promise(
      (_resolve, reject) => signal?.addEventListener("abort", () => reject(new Error("aborted"))),
    ));
    let run!: Promise<void>;
    act(() => {
      run = latest!.start(alienSearch);
    });
    const timedOut = expect(run).rejects.toThrow("tempo massimo");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(streamingSearchClientTimeoutMs);
    });

    await timedOut;
    expect(latest?.running).toBe(false);
    vi.useRealTimers();
  });

  it("supports explicit cancellation and clears the active socket", async () => {
    vi.mocked(createStreamingSearch).mockResolvedValue({
      success: true,
      session_id: "cancel",
      websocket_url: "/ws/search/cancel",
    });
    let run!: Promise<void>;
    await act(async () => {
      run = latest!.start(alienSearch);
      await Promise.resolve();
    });

    act(() => latest!.cancel());
    await expect(run).resolves.toBeUndefined();

    expect(FakeWebSocket.instances[0].closed).toBe(true);
    expect(latest?.running).toBe(false);
  });

  it("supports explicit cancellation while the session request is pending", async () => {
    vi.mocked(createStreamingSearch).mockImplementation((signal) => new Promise(
      (_resolve, reject) => signal?.addEventListener("abort", () => reject(new Error("aborted"))),
    ));
    let run!: Promise<void>;
    act(() => {
      run = latest!.start(alienSearch);
    });

    act(() => latest!.cancel());
    await expect(run).resolves.toBeUndefined();

    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(latest?.running).toBe(false);
    expect(latest?.error).toBe("");
  });

  it("preserves the exact source when all_completed rotates refs and swaps duplicate placement", async () => {
    vi.mocked(createStreamingSearch).mockResolvedValue({
      success: true,
      session_id: "selection",
      websocket_url: "/ws/search/selection",
    });
    act(() => root.render(<StreamingTableHarness />));

    let run!: Promise<void>;
    await act(async () => {
      run = latest!.start(alienSearch);
      await Promise.resolve();
    });
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emit("open");
      socket.emit("message", {
        data: JSON.stringify({
          type: "result",
          data: {
            title: "Film A",
            resolution: "1080p",
            indexer: "Prowlarr",
            size_gb: 1.5,
            source_id: "ohsid_source_a",
            torrent_ref: "ohsdl_stream_primary",
          },
        }),
      });
      socket.emit("message", {
        data: JSON.stringify({
          type: "result",
          data: {
            title: "Film A",
            resolution: "1080p",
            indexer: "Prowlarr",
            size_gb: 1.5,
            source_id: "ohsid_source_b",
            torrent_ref: "ohsdl_stream_duplicate",
          },
        }),
      });
    });
    const streamedRows = container.querySelectorAll<HTMLInputElement>(
      '[aria-label="Seleziona Film A"]',
    );
    act(() => streamedRows[1]?.click());

    act(() => {
      socket.emit("message", {
        data: JSON.stringify({
          type: "all_completed",
          filtered_results: [
            {
              title: "Film A",
              resolution: "1080p",
              indexer: "Prowlarr",
              size_gb: 1.5,
              source_id: "ohsid_source_b",
              torrent_ref: "ohsdl_final_source_b",
              duplicates: [
                {
                  title: "Film A",
                  resolution: "1080p",
                  indexer: "Prowlarr",
                  size_gb: 1.5,
                  source_id: "ohsid_source_a",
                  torrent_ref: "ohsdl_final_source_a",
                },
              ],
            },
          ],
        }),
      });
    });
    await act(async () => run);

    expect(
      container.querySelector<HTMLInputElement>('[aria-label="Seleziona Film A"]')
        ?.checked,
    ).toBe(true);
    expect(
      container.querySelector<HTMLInputElement>(
        '[aria-label="Seleziona fonte Film A"]',
      )?.checked,
    ).toBe(false);
  });

  it("rejects an explicit partial terminal instead of reporting success", async () => {
    vi.mocked(createStreamingSearch).mockResolvedValue({
      success: true,
      session_id: "partial",
      websocket_url: "/ws/search/partial",
    });

    let run!: Promise<void>;
    await act(async () => {
      run = latest!.start(alienSearch);
      await Promise.resolve();
    });
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.emit("open");
      socket.emit("message", {
        data: JSON.stringify({ type: "result", data: { title: "Available result" } }),
      });
      socket.emit("message", {
        data: JSON.stringify({
          type: "all_completed",
          status: "partial",
          message: "Storico non salvato",
          history_saved: false,
        }),
      });
    });

    await expect(run).rejects.toMatchObject({
      name: "StreamingSearchPartialError",
      message: "Storico non salvato",
      historySaved: false,
    });
    expect(latest?.running).toBe(false);
    expect(latest?.results).toEqual([{ title: "Available result" }]);
    expect(latest?.warning).toBe("Storico non salvato");
  });
});
