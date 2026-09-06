// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { deleteEmbyServer } from "@/features/configuration/api";
import { useEmbyServers } from "@/features/configuration/use-emby-servers";

vi.mock("@/features/configuration/api", () => ({
  createEmbyServer: vi.fn(),
  deleteEmbyServer: vi.fn(),
  getEmbyServers: vi.fn().mockResolvedValue({ servers: [] }),
  updateEmbyServer: vi.fn(),
}));

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void; reject: (reason: unknown) => void };

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((complete, fail) => { resolve = complete; reject = fail; });
  return { promise, reject, resolve };
}

let latest: ReturnType<typeof useEmbyServers> | undefined;

function Harness() {
  latest = useEmbyServers();
  return null;
}

describe("useEmbyServers keyed removals", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>));
  });

  afterEach(() => {
    act(() => root.unmount());
    client.clear();
    container.remove();
    latest = undefined;
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("preserves pending counters and errors across inverted completions", async () => {
    const first = deferred<Awaited<ReturnType<typeof deleteEmbyServer>>>();
    const second = deferred<Awaited<ReturnType<typeof deleteEmbyServer>>>();
    const third = deferred<Awaited<ReturnType<typeof deleteEmbyServer>>>();
    vi.mocked(deleteEmbyServer)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockReturnValueOnce(third.promise);

    act(() => {
      latest?.remove.mutate("server-a");
      latest?.remove.mutate("server-b");
      latest?.remove.mutate("server-b");
    });
    expect(latest?.deletingIds).toEqual(new Set(["server-a", "server-b"]));

    await act(async () => { second.resolve({ success: true, message: "ok" }); await second.promise; });
    expect(latest?.deletingIds.has("server-b")).toBe(true);
    await act(async () => { first.reject(new Error("A non rimosso")); await first.promise.catch(() => undefined); });

    expect(latest?.removalErrors).toEqual({ "server-a": "A non rimosso" });
    expect(latest?.deletingIds.has("server-a")).toBe(false);
    await act(async () => { third.resolve({ success: true, message: "ok" }); await third.promise; });
    expect(latest?.deletingIds.size).toBe(0);
  });
});
