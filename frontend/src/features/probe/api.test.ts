import { afterEach, describe, expect, it, vi } from "vitest";

import { getProbeQueue, retryBlacklistedProbeItem } from "@/features/probe/api";
import { setCsrfToken } from "@/lib/http";

describe("Probe API", () => {
  afterEach(() => {
    setCsrfToken("");
    vi.unstubAllGlobals();
  });

  it("loads one bounded cursor page and leaves subsequent pages explicit", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        success: true,
        queue: [{ id: 1, item_id: "first" }],
        has_more: true,
        next_cursor: 1,
      }),
      { status: 200 },
    ));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getProbeQueue("green", "libraries");

    expect(result.queue.map((item) => item.item_id)).toEqual(["first"]);
    expect(result.next_cursor).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("limit=200");
    expect(String(fetchMock.mock.calls[0][0])).toContain("cursor=0");
  });

  it("retries a blacklisted item with one atomic backend command", async () => {
    setCsrfToken("csrf");
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ success: true, message: "Queued" }),
      { status: 200 },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await retryBlacklistedProbeItem({
      serverId: "green",
      scope: "libraries",
      type: "error",
      itemId: "movie-1",
      mediaSourceId: "source-a",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/emby/probe/retry");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
  });
});
