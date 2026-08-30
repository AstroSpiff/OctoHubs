import { describe, expect, it } from "vitest";

import {
  collectionSourceFromValue,
  detectCollectionSourceType,
  hasCollectionSourceInventoryDraft,
} from "@/features/collections/collection-source-input";

describe("collection source input", () => {
  it("normalizes a pasted Trakt list and selects its provider", () => {
    expect(
      collectionSourceFromValue(
        "https://trakt.tv/users/Example/lists/watch-later?sort=rank#top",
      ),
    ).toEqual({
      sourceType: "trakt_list",
      sourceValue: "example/watch-later?sort=rank",
    });
  });

  it("recognizes the other supported provider URLs without rewriting them", () => {
    expect(
      collectionSourceFromValue("https://www.themoviedb.org/collection/121867"),
    ).toEqual({
      sourceType: "tmdb_collection",
      sourceValue: "https://www.themoviedb.org/collection/121867",
    });
    expect(detectCollectionSourceType("https://mdblist.com/lists/demo")).toBe(
      "mdblist",
    );
  });

  it("does not invent a source for a manual value", () => {
    expect(collectionSourceFromValue("123456")).toBeNull();
  });

  it("keeps manual source fields protected while they contain a draft", () => {
    expect(hasCollectionSourceInventoryDraft("", "   ")).toBe(false);
    expect(hasCollectionSourceInventoryDraft("Lista estate", "")).toBe(true);
    expect(hasCollectionSourceInventoryDraft("", "https://example.test/list")).toBe(true);
  });
});
