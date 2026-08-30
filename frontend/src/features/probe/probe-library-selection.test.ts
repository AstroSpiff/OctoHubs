import { describe, expect, it } from "vitest";

import {
  librarySelectionAfterBucketToggle,
  librarySelectionState,
  selectedAvailableLibraryIds,
} from "@/features/probe/probe-library-selection";

describe("librarySelectionAfterBucketToggle", () => {
  it("adds only the selected library category without losing the rest", () => {
    expect(
      librarySelectionAfterBucketToggle(["series"], ["movie-a", "movie-b"], true),
    ).toEqual(["series", "movie-a", "movie-b"]);
  });

  it("removes only the deselected library category", () => {
    expect(
      librarySelectionAfterBucketToggle(
        ["movie-a", "movie-b", "series"],
        ["movie-a", "movie-b"],
        false,
      ),
    ).toEqual(["series"]);
  });

  it("reports a partial selection for the parent and category toggles", () => {
    expect(librarySelectionState(["movie-a"], ["movie-a", "movie-b"]))
      .toEqual({
        selectedCount: 1,
        total: 2,
        checked: false,
        indeterminate: true,
      });
  });

  it("drops selections for libraries that no longer exist", () => {
    expect(
      selectedAvailableLibraryIds(
        ["movie-a", "removed-library", "movie-a"],
        ["movie-a", "series-a"],
      ),
    ).toEqual(["movie-a"]);
  });
});
