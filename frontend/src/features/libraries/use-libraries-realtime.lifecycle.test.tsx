// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ScanJob } from "@/features/libraries/types";
import { useLibrariesRealtime } from "@/features/libraries/use-libraries-realtime";

type Listener = (event: { data?: unknown }) => void;

class FakeSocket {
  static readonly CLOSED = 3;
  static instances: FakeSocket[] = [];
  readyState = 1;
  closed = false;
  private readonly listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    void url;
    FakeSocket.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) || []), listener]);
  }

  send(payload: string) {
    void payload;
  }

  close() {
    this.closed = true;
    this.readyState = FakeSocket.CLOSED;
  }

  emit(type: string) {
    for (const listener of this.listeners.get(type) || []) listener({});
  }
}

class FakeEventSource {
  onmessage: ((event: { data: string }) => void) | null = null;
  close() {}
}

function Harness() {
  useLibrariesRealtime(
    [{ job_id: "job-one" } as ScanJob],
    {
      onConfigurationChange: () => undefined,
      onLibraryChange: () => undefined,
      onScanChange: () => undefined,
    },
  );
  return null;
}

describe("libraries WebSocket lifecycle", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let visibility: DocumentVisibilityState;
  let mounted: boolean;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    FakeSocket.instances = [];
    visibility = "visible";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibility,
    });
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("crypto", { randomUUID: () => "client-id" });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    mounted = true;
  });

  afterEach(() => {
    if (mounted) act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("cancels a pending reconnect before visibility opens a replacement", () => {
    act(() => root.render(<Harness />));
    expect(FakeSocket.instances).toHaveLength(1);

    act(() => FakeSocket.instances[0].emit("close"));
    visibility = "hidden";
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    visibility = "visible";
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(FakeSocket.instances).toHaveLength(2);

    act(() => vi.advanceTimersByTime(2_100));
    expect(FakeSocket.instances).toHaveLength(2);

    act(() => root.unmount());
    mounted = false;
    expect(FakeSocket.instances[1].closed).toBe(true);
  });
});
