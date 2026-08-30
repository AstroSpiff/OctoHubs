import { describe, expect, it } from "vitest";

import { manualSearchInputFromHistory } from "@/features/research/manual-search-history";

describe("manual search history", () => {
  it("restores the complete context saved by a current streaming search", () => {
    expect(manualSearchInputFromHistory({
      id: 1,
      search_context: {
        query: "Severance",
        media_type: "tv",
        indexers: ["prowlarr", "jackett"],
        tmdb_id: 95396,
        seasons: [1, 2],
        custom_rules: { search_rules: { query_terms: ["2160p"] }, target_languages: ["ita"], exclude_tags: ["cam"] },
      },
    })).toEqual({
      query: "Severance",
      mediaType: "tv",
      indexers: ["prowlarr", "jackett"],
      tmdbId: 95396,
      seasons: [1, 2],
      customRules: { search_rules: { query_terms: ["2160p"] }, target_languages: ["ita"], exclude_tags: ["cam"] },
    });
  });

  it("derives a replayable search from a legacy history entry", () => {
    expect(manualSearchInputFromHistory({
      id: 2,
      items: [{ title: "Foundation", media_type: "mixed", queries: [{ indexer: "jackett" }, { indexer: "prowlarr" }] }],
    })).toEqual({ query: "Foundation", mediaType: "unknown", indexers: ["jackett", "prowlarr"], seasons: [] });
  });
});
