import { describe, expect, it } from "vitest";

import { latestFetchLimits } from "@/features/emby-latest/latest-fetch-limits";

describe("latestFetchLimits", () => {
  it("matches the legacy fetch limits from configured content limits and servers", () => {
    expect(latestFetchLimits({ max_movies: 50, max_series: 25 }, 5)).toEqual({
      perServerLimit: 50,
      limit: 250,
    });
  });

  it("keeps a safe fallback and caps the API request maximum", () => {
    expect(latestFetchLimits(undefined, 20)).toEqual({
      perServerLimit: 100,
      limit: 1_000,
    });
  });
});
