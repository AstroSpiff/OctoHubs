// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveServerActions } from "@/features/emby-live/use-live-server-actions";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let actions: ReturnType<typeof useLiveServerActions> | undefined;

function Harness({ refreshServer }: { refreshServer: (serverId: string) => Promise<void> }) {
  actions = useLiveServerActions({
    confirm: async () => true,
    refreshLive: () => undefined,
    refreshServer,
  });
  return null;
}

describe("useLiveServerActions", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    actions = undefined;
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("admits only one manual refresh per server", async () => {
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const refreshServer = vi.fn(() => pending);
    act(() => root.render(
      <QueryClientProvider client={queryClient}>
        <Harness refreshServer={refreshServer} />
      </QueryClientProvider>,
    ));

    let first!: Promise<void>;
    let duplicate!: Promise<void>;
    act(() => {
      first = actions!.requestRefresh("green");
      duplicate = actions!.requestRefresh("green");
    });
    await duplicate;
    expect(refreshServer).toHaveBeenCalledOnce();
    expect(actions?.refreshingServerIds).toEqual(new Set(["green"]));

    await act(async () => {
      finish();
      await first;
    });
    expect(actions?.refreshingServerIds.size).toBe(0);
  });
});
