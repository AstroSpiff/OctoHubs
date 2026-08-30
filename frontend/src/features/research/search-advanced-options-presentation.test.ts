import { describe, expect, it } from "vitest";

import { visibleSortMediaTypes } from "@/features/research/search-advanced-options-presentation";

describe("advanced search options presentation", () => {
  it("shows both sort groups when the media type is not known", () => {
    expect(visibleSortMediaTypes()).toEqual(["movie", "tv"]);
    expect(visibleSortMediaTypes("unknown")).toEqual(["movie", "tv"]);
  });

  it("keeps the sort controls relevant to the selected media type", () => {
    expect(visibleSortMediaTypes("movie")).toEqual(["movie"]);
    expect(visibleSortMediaTypes("tv")).toEqual(["tv"]);
  });
});
