import { describe, expect, it } from "vitest";

import {
  setLibraryAccessMode,
  toggleLibraryAccessItem,
  unresolvedLibraryAccessIds,
} from "@/features/user-settings/library-access-state";

const libraries = [
  { id: "movies", alt_ids: ["legacy-movies"], group_key: "movies:main" },
  { id: "shows", group_key: "shows:main" },
];

describe("library access state", () => {
  it("seeds custom mode with every visible library when leaving all-libraries mode", () => {
    expect(setLibraryAccessMode({ mode: "all", items: [], groups: {} }, libraries, "custom")).toEqual({
      mode: "custom",
      items: ["movies", "shows"],
      groups: { "movies:main": true, "shows:main": true },
    });
  });

  it("preserves a matching legacy ID and recalculates groups when selection changes", () => {
    const next = toggleLibraryAccessItem(
      { mode: "custom", items: ["legacy-movies"], groups: { "movies:main": true } },
      libraries,
      libraries[1],
      true,
    );

    expect(next).toEqual({
      mode: "custom",
      items: ["legacy-movies", "shows"],
      groups: { "movies:main": true, "shows:main": true },
    });
    expect(unresolvedLibraryAccessIds({ mode: "custom", items: ["missing"], groups: {} }, libraries)).toEqual(["missing"]);
  });
});
