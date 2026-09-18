// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceCapabilityBoundary } from "@/components/app-shell";
import { getProbeQueueGroupItems } from "@/features/probe/api";
import { ProbeQueueGroups } from "@/features/probe/components/probe-queue-groups";
import type { ProbeQueueGroup, ProbeQueueItem } from "@/features/probe/types";

vi.mock("@/features/probe/api", () => ({
  getProbeQueueGroupItems: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

const groups: ProbeQueueGroup[] = [
  {
    server_id: "green",
    library_id: "movies",
    library_name: "Film",
    group_type: "movie",
    group_id: "movie-1",
    title: "Film Uno",
    file_count: 2,
  },
  {
    server_id: "green",
    library_id: "movies",
    library_name: "Film",
    group_type: "movie",
    group_id: "movie-2",
    title: "Film Due",
    file_count: 1,
  },
];

describe("ProbeQueueGroups lazy details", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("keeps one detail request in memory and discards it on switch and close", async () => {
    const first = deferred<{ success: boolean; queue: ProbeQueueItem[] }>();
    const second = deferred<{ success: boolean; queue: ProbeQueueItem[] }>();
    const third = deferred<{ success: boolean; queue: ProbeQueueItem[] }>();
    vi.mocked(getProbeQueueGroupItems)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockReturnValueOnce(third.promise);

    await act(async () => {
      root.render(
        <WorkspaceCapabilityBoundary accessState="editor">
          <ProbeQueueGroups
            groups={groups}
            scope="libraries"
            serverNames={{ green: "Green" }}
            busy={false}
            onRemove={vi.fn(async () => undefined)}
          />
        </WorkspaceCapabilityBoundary>,
      );
    });

    const titleButtons = [...container.querySelectorAll<HTMLButtonElement>(
      ".probe-queue-title-summary",
    )];
    await act(async () => titleButtons[0].click());
    expect(getProbeQueueGroupItems).toHaveBeenCalledTimes(1);

    const firstSignal = vi.mocked(getProbeQueueGroupItems).mock.calls[0][2];
    await act(async () => titleButtons[1].click());
    expect(firstSignal?.aborted).toBe(true);
    expect(getProbeQueueGroupItems).toHaveBeenCalledTimes(2);
    expect(container.querySelectorAll(".probe-queue-title-details")).toHaveLength(1);

    await act(async () => {
      second.resolve({
        success: true,
        queue: [{ item_id: "movie-2", path: "/second.mkv" }],
      });
      await second.promise;
    });
    expect(container.textContent).toContain("/second.mkv");

    await act(async () => {
      first.resolve({
        success: true,
        queue: [{ item_id: "movie-1", path: "/stale-first.mkv" }],
      });
      await first.promise;
    });
    expect(container.textContent).not.toContain("/stale-first.mkv");

    await act(async () => titleButtons[1].click());
    expect(container.querySelector(".probe-queue-title-details")).toBeNull();
    expect(container.textContent).not.toContain("/second.mkv");

    await act(async () => titleButtons[1].click());
    expect(getProbeQueueGroupItems).toHaveBeenCalledTimes(3);
    third.resolve({ success: true, queue: [] });
  });
});
