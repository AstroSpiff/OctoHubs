import { describe, expect, it } from "vitest";

import { groupProbeItemsByLibrary } from "@/features/probe/probe-grouping";

describe("groupProbeItemsByLibrary", () => {
  it("keeps identically named libraries separate across Emby servers", () => {
    const groups = groupProbeItemsByLibrary(
      [
        {
          item_id: "one",
          server_id: "green",
          library_id: "films",
          library_name: "Film",
        },
        {
          item_id: "two",
          server_id: "purple",
          library_id: "films",
          library_name: "Film",
        },
        {
          item_id: "three",
          server_id: "green",
          library_id: "shows",
          library_name: "Serie",
        },
      ],
      { green: "Green", purple: "Purple" },
    );

    expect(groups.map((group) => group.label)).toEqual([
      "Green - Film",
      "Green - Serie",
      "Purple - Film",
    ]);
    expect(groups.map((group) => group.items.length)).toEqual([1, 1, 1]);
  });
});
