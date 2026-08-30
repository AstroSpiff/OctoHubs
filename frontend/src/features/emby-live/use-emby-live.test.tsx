// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getEmbyLiveSnapshot } from "@/features/emby-live/api";
import type { EmbyLiveSnapshot } from "@/features/emby-live/types";
import { useEmbyLive } from "@/features/emby-live/use-emby-live";

vi.mock("@/features/emby-live/api", () => ({
  getEmbyLiveSnapshot: vi.fn(),
  getEmbyServerStatus: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }
}

let latest: ReturnType<typeof useEmbyLive> | undefined;

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function snapshot(serverId: string): EmbyLiveSnapshot {
  return {
    success: true,
    servers: {
      [serverId]: {
        server: { id: serverId, name: serverId, enabled: true },
        status: { ok: true },
        running_tasks: [],
        tasks_error: null,
        streams: [],
        streams_error: null,
      },
    },
  };
}

function Harness() {
  latest = useEmbyLive();
  return null;
}

describe("useEmbyLive", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
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

  it("does not let a slow HTTP fallback overwrite a newer SSE snapshot", async () => {
    const fallback = deferred<EmbyLiveSnapshot>();
    let fallbackSignal: AbortSignal | undefined;
    vi.mocked(getEmbyLiveSnapshot).mockImplementation((signal) => {
      fallbackSignal = signal;
      return fallback.promise;
    });
    const source = FakeEventSource.instances[0];
    const sseSnapshot = snapshot("sse-new");

    act(() => source.onerror?.());
    expect(getEmbyLiveSnapshot).toHaveBeenCalledOnce();

    act(() => source.onmessage?.({ data: JSON.stringify(sseSnapshot) }));
    expect(fallbackSignal?.aborted).toBe(true);

    await act(async () => {
      fallback.resolve(snapshot("http-old"));
      await fallback.promise;
      await Promise.resolve();
    });

    expect(Object.keys(latest?.snapshot?.servers || {})).toEqual(["sse-new"]);
    expect(latest?.connection).toBe("connected");
    expect(latest?.error).toBeNull();
  });

  it("invalidates an in-flight fallback when refresh creates a new generation", async () => {
    const fallback = deferred<EmbyLiveSnapshot>();
    let fallbackSignal: AbortSignal | undefined;
    vi.mocked(getEmbyLiveSnapshot).mockImplementation((signal) => {
      fallbackSignal = signal;
      return fallback.promise;
    });
    const oldSource = FakeEventSource.instances[0];

    act(() => oldSource.onerror?.());
    act(() => latest?.refresh());

    expect(oldSource.closed).toBe(true);
    expect(fallbackSignal?.aborted).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(2);

    const currentSource = FakeEventSource.instances[1];
    act(() => currentSource.onmessage?.({ data: JSON.stringify(snapshot("current")) }));
    await act(async () => {
      fallback.resolve(snapshot("superseded"));
      await fallback.promise;
      await Promise.resolve();
    });

    expect(Object.keys(latest?.snapshot?.servers || {})).toEqual(["current"]);
    expect(latest?.connection).toBe("connected");
  });
});
