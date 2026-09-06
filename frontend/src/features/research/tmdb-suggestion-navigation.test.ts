import { describe, expect, it } from "vitest";

import {
  nextTmdbSuggestionIndex,
  tmdbSuggestionDomId,
} from "@/features/research/tmdb-suggestion-navigation";

describe("TMDB suggestion navigation", () => {
  it("starts at either edge and wraps within the available suggestions", () => {
    expect(nextTmdbSuggestionIndex(-1, 1, 3)).toBe(0);
    expect(nextTmdbSuggestionIndex(-1, -1, 3)).toBe(2);
    expect(nextTmdbSuggestionIndex(2, 1, 3)).toBe(0);
    expect(nextTmdbSuggestionIndex(0, -1, 3)).toBe(2);
  });

  it("has no active option when no suggestions are available", () => {
    expect(nextTmdbSuggestionIndex(0, 1, 0)).toBe(-1);
  });

  it("keeps movie and TV option ids distinct when TMDB ids overlap", () => {
    expect(tmdbSuggestionDomId("movie", 42)).toBe("tmdb-suggestion-movie-42");
    expect(tmdbSuggestionDomId("tv", 42)).toBe("tmdb-suggestion-tv-42");
  });
});
