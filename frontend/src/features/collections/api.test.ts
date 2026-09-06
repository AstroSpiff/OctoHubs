import { afterEach, describe, expect, it, vi } from "vitest";

import {
  collectionOperationFromSnapshot,
  getTraktLists,
  requestCollectionItemFromJellyseerr,
} from "@/features/collections/api";
import { setCsrfToken } from "@/lib/http";


describe("collection Jellyseerr requests", () => {
  afterEach(() => {
    setCsrfToken("");
    vi.unstubAllGlobals();
  });

  it("uses the camelCase aliases required by the API model", async () => {
    setCsrfToken("csrf");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await requestCollectionItemFromJellyseerr({ tmdb_id: 42, media_type: "movie" });

    const [, options] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(options.body))).toEqual({ mediaId: 42, mediaType: "movie" });
  });
});

describe("collection source list refresh", () => {
  afterEach(() => {
    setCsrfToken("");
    vi.unstubAllGlobals();
  });

  it("starts the tracked refresh with POST and forwards cancellation", async () => {
    setCsrfToken("csrf");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, lists: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await getTraktLists(controller.signal);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/emby/collections/trakt-lists");
    expect(options.method).toBe("POST");
    expect(options.signal).toBe(controller.signal);
  });
});

describe("collection operation snapshots", () => {
  it("fails immediately when the requested operation has left the registry", () => {
    expect(() => collectionOperationFromSnapshot([], "missing-operation"))
      .toThrow("non è più disponibile");
  });

  it("returns only the matching operation", () => {
    const operation = { id: "wanted", status: "running" } as Parameters<typeof collectionOperationFromSnapshot>[0][number];
    expect(collectionOperationFromSnapshot([
      { id: "other", status: "success" } as typeof operation,
      operation,
    ], "wanted")).toBe(operation);
  });
});
