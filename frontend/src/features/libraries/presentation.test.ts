import { describe, expect, it } from "vitest";

import {
  hiddenLibraryGroupName,
  formatLibraryDuration,
  libraryEntryScanActivity,
  libraryGroupScanActivity,
  libraryGroupOrder,
  latestLibraryGroupHistory,
  libraryScanProgress,
  libraryScanStatusSeverity,
  libraryTypeBucket,
  moveLibraryOrderItem,
  moveLibraryOrderItemTo,
  visibleLibraryGroups,
} from "@/features/libraries/presentation";

describe("library presentation", () => {
  it("groups unknown types under other", () => {
    expect(libraryTypeBucket("boxsets")).toBe("other");
    expect(libraryTypeBucket("movies")).toBe("movies");
  });

  it("filters groups by their library names", () => {
    const groups = [
      {
        group_name: "Cinema",
        collection_type: "movies",
        servers: ["a"],
        libraries: [{ server_id: "a", library_name: "Film 4K" }],
      },
    ];
    expect(
      visibleLibraryGroups(groups, { search: "4k", type: "all" }),
    ).toHaveLength(1);
  });

  it("does not show groups intentionally marked as hidden", () => {
    const groups = [
      {
        group_name: hiddenLibraryGroupName,
        collection_type: "movies",
        servers: ["a"],
        libraries: [{ server_id: "a", library_name: "Archivio" }],
      },
      {
        group_name: "Cinema",
        collection_type: "movies",
        servers: ["a"],
        libraries: [{ server_id: "a", library_name: "Film" }],
      },
    ];
    expect(
      visibleLibraryGroups(groups, { search: "", type: "all" }),
    ).toHaveLength(1);
  });

  it("formats completed scan durations without exposing raw timestamps", () => {
    expect(formatLibraryDuration("2026-08-11T10:00:00Z", "2026-08-11T10:01:05Z")).toBe("1m 5s");
    expect(formatLibraryDuration()).toBe("Durata non disponibile");
  });

  it("normalizes final scan progress and its status severity", () => {
    expect(libraryScanProgress(0.72)).toBe(72);
    expect(libraryScanProgress(72)).toBe(72);
    expect(libraryScanProgress()).toBeUndefined();
    expect(libraryScanStatusSeverity("completed")).toBe("ok");
    expect(libraryScanStatusSeverity("error")).toBe("error");
  });

  it("maps tracked progress to both the group and its matching library", () => {
    const group = {
      group_name: "Cinema",
      collection_type: "movies",
      servers: ["green"],
      libraries: [{ server_id: "green", library_id: "films", library_name: "Film" }],
    };
    const jobs = [{ job_id: "job-1", server_id: "green", library_ids: ["films"], group_name: "Cinema", status: "active", progress: 0.42 }];

    expect(libraryGroupScanActivity(group, jobs)).toMatchObject({ status: "active", progress: 42, jobCount: 1 });
    expect(libraryEntryScanActivity(group.libraries[0], jobs)).toMatchObject({ status: "active", progress: 42 });
  });

  it("selects the newest completed activity for the matching group only", () => {
    const group = { group_name: "Cinema", collection_type: "movies", servers: [], libraries: [] };
    expect(latestLibraryGroupHistory(group, [
      { id: "first", group_name: "Cinema", status: "completed", completed_at: "2026-08-20T10:00:00Z" },
      { id: "latest", group_name: "Cinema", status: "completed", completed_at: "2026-08-21T10:00:00Z" },
      { id: "other", group_name: "Serie", status: "error", completed_at: "2026-08-22T10:00:00Z" },
    ])).toMatchObject({ id: "latest" });
  });

  it("keeps ordering scoped to each library type and moves only valid entries", () => {
    const groups = [
      { group_name: "Cinema", collection_type: "movies", servers: [], libraries: [] },
      { group_name: "Documentari", collection_type: "movies", servers: [], libraries: [] },
      { group_name: "Serie", collection_type: "tvshows", servers: [], libraries: [] },
    ];
    expect(libraryGroupOrder(groups)).toEqual([
      { collection_type: "movies", group_name: "Cinema", position: 0 },
      { collection_type: "movies", group_name: "Documentari", position: 1 },
      { collection_type: "tvshows", group_name: "Serie", position: 0 },
    ]);
    expect(moveLibraryOrderItem(["uno", "due"], 0, 1)).toEqual(["due", "uno"]);
    expect(moveLibraryOrderItem(["uno", "due"], 0, -1)).toEqual(["uno", "due"]);
  });

  it("moves an item before or after a drop target without mutating the draft", () => {
    const original = ["a", "b", "c", "d"];

    expect(moveLibraryOrderItemTo(original, 0, 2)).toEqual([
      "b",
      "a",
      "c",
      "d",
    ]);
    expect(moveLibraryOrderItemTo(original, 0, 2, true)).toEqual([
      "b",
      "c",
      "a",
      "d",
    ]);
    expect(original).toEqual(["a", "b", "c", "d"]);
  });
});
