import { describe, expect, it } from "vitest";

import {
  libraryAssociationDraftMatches,
  libraryGroupOrderMatches,
  libraryServerOrderMatches,
} from "@/features/libraries/library-dialog-draft";

describe("library dialog drafts", () => {
  it("compares association drafts by their normalized values", () => {
    expect(
      libraryAssociationDraftMatches(
        { "green:films": " Cinema ", "purple:films": "" },
        { "green:films": "Cinema" },
      ),
    ).toBe(true);
    expect(
      libraryAssociationDraftMatches(
        { "green:films": "Cinema nuovo" },
        { "green:films": "Cinema" },
      ),
    ).toBe(false);
  });

  it("detects changes to either group or server ordering", () => {
    const groups = [
      { group_name: "Cinema", collection_type: "movies", servers: [], libraries: [] },
      { group_name: "Serie", collection_type: "tvshows", servers: [], libraries: [] },
    ];
    const servers = [
      { id: "green", name: "Green" },
      { id: "purple", name: "Purple" },
    ];

    expect(libraryGroupOrderMatches(groups, groups)).toBe(true);
    expect(libraryGroupOrderMatches([...groups].reverse(), groups)).toBe(false);
    expect(libraryServerOrderMatches(servers, servers)).toBe(true);
    expect(libraryServerOrderMatches([...servers].reverse(), servers)).toBe(false);
  });
});
