// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createStreamingSearch } from "@/features/research/api";
import { useStreamingSearch } from "@/features/research/use-streaming-search";

vi.mock("@/features/research/api", () => ({
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
});
