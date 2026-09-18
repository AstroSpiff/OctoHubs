import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getProbeQueue,
  getProbeQueueGroupItems,
  getProbeQueueGroups,
  retryBlacklistedProbeItem,
} from "@/features/probe/api";
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

  it("loads every title summary separately from one selected title's files", async () => {
    const group = {
      server_id: "green",
      library_id: "movies",
      library_name: "Film",
      group_type: "movie" as const,
      group_id: "movie-1",
      title: "Film di prova",
      year: 2026,
      file_count: 2,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ success: true, groups: [group] }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            success: true,
            queue: [
              { item_id: "movie-1", media_source_id: "source-a" },
              { item_id: "movie-1", media_source_id: "source-b" },
            ],
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const summaries = await getProbeQueueGroups("green", "libraries");
    const details = await getProbeQueueGroupItems(group, "libraries");

    expect(summaries.groups[0].file_count).toBe(2);
    expect(details.queue).toHaveLength(2);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/queue/groups?");
    expect(String(fetchMock.mock.calls[0][0])).not.toContain("limit=");
    expect(String(fetchMock.mock.calls[1][0])).toContain("/queue/group-items?");
    expect(String(fetchMock.mock.calls[1][0])).toContain("group_id=movie-1");
  });

  it("does not serialize a missing series year as the text null", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, queue: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getProbeQueueGroupItems(
      {
        server_id: "green",
        library_id: "series",
        library_name: "Serie TV",
        group_type: "series",
        group_id: "Serie completa",
        title: "Serie completa",
        year: null,
        file_count: 12,
      },
      "libraries",
    );

    const requestUrl = String(fetchMock.mock.calls[0][0]);
    expect(requestUrl).toContain("group_type=series");
    expect(requestUrl).not.toContain("year=null");
    expect(requestUrl).not.toContain("year=");
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
