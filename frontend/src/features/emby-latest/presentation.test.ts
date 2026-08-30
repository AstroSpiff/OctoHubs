import { describe, expect, it } from "vitest";

import {
  latestItemsForServer,
  latestPreviewItemLabel,
} from "@/features/emby-latest/presentation";

describe("latest presentation", () => {
  const items = [
    {
      server_id: "green",
      server_name: "Green",
      title: "Film",
      year: 2026,
      update_label: "Nuova versione",
      added_at: "2026-08-12T10:00:00Z",
    },
    { server_id: "purple", server_name: "Purple", title: "Serie" },
  ];

  it("keeps preview choices aligned with the selected server", () => {
    expect(latestItemsForServer(items, "green")).toEqual([items[0]]);
    expect(latestItemsForServer(items, "all")).toEqual(items);
  });

  it("includes the release context in a preview choice", () => {
    expect(latestPreviewItemLabel(items[0])).toBe(
      "Film (2026) · Nuova versione · Green · 12/08/26",
    );
  });
});
