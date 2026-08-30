import { afterEach, describe, expect, it, vi } from "vitest";

import { requestCollectionItemFromJellyseerr } from "@/features/collections/api";
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
