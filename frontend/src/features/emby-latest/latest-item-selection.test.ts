import { describe, expect, it } from "vitest";

import {
  latestItemSelectionKey,
  latestPreviewRequestKey,
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

  it("fingerprints preview content canonically and includes metadata changes", () => {
    const first = {
      server_id: "green",
      item_id: "movie-1",
      title: "Film",
      overview: "Prima sinossi",
      changes: [{ quality: "1080p", video_codec: "H264" }],
      image_url: "/api/emby/green/items/movie-1/images/primary",
    };
    const reordered = {
      image_url: "/api/emby/green/items/movie-1/images/primary",
      changes: [{ video_codec: "H264", quality: "1080p" }],
      overview: "Prima sinossi",
      title: "Film",
      item_id: "movie-1",
      server_id: "green",
    };
    const updated = {
      ...first,
      overview: "Sinossi aggiornata",
      changes: [{ quality: "2160p", video_codec: "HEVC" }],
      image_url: "/api/emby/green/items/movie-1/images/primary?tag=new",
    };

    expect(
      latestPreviewRequestKey("{{ overview }}", { movie: first }),
    ).toBe(latestPreviewRequestKey("{{ overview }}", { movie: reordered }));
    expect(
      latestPreviewRequestKey("{{ overview }}", { movie: first }),
    ).not.toBe(latestPreviewRequestKey("{{ overview }}", { movie: updated }));
  });
});
