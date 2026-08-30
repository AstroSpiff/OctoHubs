import { describe, expect, it } from "vitest";

import {
  libraryItemIsSelected,
  toggleLibraryItem,
  unresolvedLibraryIds,
} from "@/features/user-settings/library-multi-selection";

const library = {
  id: "movies",
  name: "Film",
  alt_ids: ["legacy-movies", "view-movies"],
};

describe("library multi selection", () => {
  it("recognizes legacy aliases and removes every equivalent identifier when unchecked", () => {
    expect(libraryItemIsSelected(library, new Set(["legacy-movies"]))).toBe(true);
    expect(toggleLibraryItem(["legacy-movies", "movies", "other"], library, false)).toEqual(["other"]);
  });

  it("keeps unresolved saved identifiers visible instead of silently dropping them", () => {
    expect(unresolvedLibraryIds(["legacy-movies", "missing"], [library])).toEqual(["missing"]);
  });
});
