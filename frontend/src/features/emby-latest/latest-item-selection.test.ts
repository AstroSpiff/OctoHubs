import { describe, expect, it } from "vitest";

import {
  latestItemSelectionKey,
  reconcileLatestItemSelection,
} from "@/features/emby-latest/latest-item-selection";

describe("latest item selection", () => {
  const items = [
    { server_id: "green", item_id: "movie-1", title: "Film" },
    { server_id: "purple", item_id: "movie-2", title: "Serie" },
  ];

  it("keeps the selected item when it is still present after a refresh", () => {
    const selected = latestItemSelectionKey(items[1], 1);

    expect(reconcileLatestItemSelection(items, selected)).toBe(selected);
  });

  it("selects a valid item when the previous cache entry is gone", () => {
    expect(reconcileLatestItemSelection(items, "green-removed")).toBe(
      "green-movie-1",
    );
    expect(reconcileLatestItemSelection([], "green-movie-1")).toBe("");
  });

  it("keeps distinct updates for the same Emby item selectable", () => {
    const updates = [
      {
        server_id: "green",
        item_id: "movie-1",
        batch_id: "first",
        added_at: "2026-08-01T10:00:00Z",
      },
      {
        server_id: "green",
        item_id: "movie-1",
        batch_id: "second",
        added_at: "2026-08-02T10:00:00Z",
      },
    ];

    expect(latestItemSelectionKey(updates[0], 0)).not.toBe(
      latestItemSelectionKey(updates[1], 1),
    );
  });
});
