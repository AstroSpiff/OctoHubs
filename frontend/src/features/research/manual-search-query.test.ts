import { describe, expect, it } from "vitest";

import { manualSearchFromQuery, normalizeManualSearchMediaType } from "@/features/research/manual-search-query";

describe("manual search query", () => {
  it("restores a collection item in the independent search form", () => {
    expect(manualSearchFromQuery("?independent_query=Severance&independent_media_type=tv"))
      .toEqual({ query: "Severance", mediaType: "tv" });
  });

  it("normalizes legacy media type aliases and ignores blank searches", () => {
    expect(normalizeManualSearchMediaType("film")).toBe("movie");
    expect(manualSearchFromQuery("?independent_query=%20%20")).toBeNull();
  });
});
