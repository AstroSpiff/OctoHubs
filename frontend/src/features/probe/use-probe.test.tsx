// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getProbeBlacklist, getProbeHistory, getProbeQueue } from "@/features/probe/api";
import { useProbeScopeData } from "@/features/probe/use-probe";

vi.mock("@/features/probe/api", () => ({
  deleteProbeBlacklist: vi.fn(),
  deleteProbeHistory: vi.fn(),
  deleteProbeQueue: vi.fn(),
  getProbeBlacklist: vi.fn(),
  getProbeConfig: vi.fn(),
  getProbeHistory: vi.fn(),
  getProbeLibraries: vi.fn(),
  getProbeQueue: vi.fn(),
  retryBlacklistedProbeItem: vi.fn(),
  retryProbeItem: vi.fn(),
  runProbeAction: vi.fn(),
  saveProbeConfig: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let latestData: ReturnType<typeof useProbeScopeData> | undefined;

function Harness() {
  latestData = useProbeScopeData("libraries", ["green"], "queue");
  return null;
}

describe("useProbeScopeData", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latestData = undefined;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    queryClient.clear();
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("fetches only the active dataset and loads further cursor pages explicitly", async () => {
    vi.mocked(getProbeQueue).mockImplementation(async (_serverId, _scope, cursor) =>
      cursor === 0
        ? {
            success: true,
            queue: [{ id: 1, item_id: "first" }],
            has_more: true,
            next_cursor: 1,
          }
        : {
            success: true,
            queue: [{ id: 2, item_id: "second" }],
            has_more: false,
            next_cursor: null,
          },
    );

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <Harness />
        </QueryClientProvider>,
      );
    });
    for (let attempt = 0; attempt < 10 && !latestData?.queue.isSuccess; attempt += 1) {
      await act(async () => {
        await new Promise((resolve) => window.setTimeout(resolve, 0));
      });
    }

    expect(getProbeQueue).toHaveBeenCalledTimes(1);
    expect(getProbeHistory).not.toHaveBeenCalled();
    expect(getProbeBlacklist).not.toHaveBeenCalled();
    expect(latestData?.queue.data.map((item) => item.item_id)).toEqual(["first"]);
    expect(latestData?.queue.hasNextPage).toBe(true);

    await act(async () => {
      await latestData?.queue.fetchNextPage();
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    expect(getProbeQueue).toHaveBeenCalledTimes(2);
    expect(vi.mocked(getProbeQueue).mock.calls[1][2]).toBe(1);
    expect(latestData?.queue.data.map((item) => item.item_id)).toEqual([
      "first",
      "second",
    ]);
  });
});
