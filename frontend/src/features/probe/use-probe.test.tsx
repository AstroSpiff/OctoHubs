// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getProbeBlacklist,
  getProbeHistory,
  getProbeQueueGroups,
} from "@/features/probe/api";
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
  getProbeQueueGroupItems: vi.fn(),
  getProbeQueueGroups: vi.fn(),
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

  it("fetches every queue title summary without paging file rows", async () => {
    vi.mocked(getProbeQueueGroups).mockResolvedValue({
      success: true,
      groups: [
        {
          server_id: "green",
          library_id: "movies",
          group_type: "movie",
          group_id: "first",
          title: "First",
          file_count: 275,
        },
      ],
    });

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

    expect(getProbeQueueGroups).toHaveBeenCalledTimes(1);
    expect(getProbeQueueGroups).toHaveBeenCalledWith(
      "green",
      "libraries",
      expect.any(AbortSignal),
    );
    expect(getProbeHistory).not.toHaveBeenCalled();
    expect(getProbeBlacklist).not.toHaveBeenCalled();
    expect(latestData?.queue.data.map((item) => item.group_id)).toEqual(["first"]);
    expect(latestData?.queue.data[0].file_count).toBe(275);
    expect(latestData?.queue.hasNextPage).toBe(false);
  });
});
