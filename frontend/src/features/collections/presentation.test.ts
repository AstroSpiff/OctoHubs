import { describe, expect, it } from "vitest";

import { canRequestCollectionItem, collectionMarkers, collectionPosterUrl, collectionSyncLabel, collectionSyncSeverity, visibleCollections } from "@/features/collections/presentation";
import type { EmbyCollection } from "@/features/collections/types";

describe("collection presentation", () => {
  it("normalizes sync status for Italian UI", () => {
    expect(collectionSyncLabel("partial")).toBe("Parziale");
    expect(collectionSyncSeverity("error")).toBe("error");
    expect(collectionSyncSeverity(null)).toBe("neutral");
  });

  it("filters collections needing attention", () => {
    const collections: EmbyCollection[] = [
      { id: "1", name: "A", enabled: true, last_sync_status: "success" },
      { id: "2", name: "B", enabled: true, last_sync_status: "warning" },
    ];
    expect(visibleCollections(collections, { search: "", status: "attention", sort: "name" }).map(({ id }) => id)).toEqual(["2"]);
  });

  it("offers Jellyseerr only for items with a TMDB id and media type", () => {
    expect(canRequestCollectionItem({ provider_key: "tmdb", provider_id: "12", media_type: "movie" })).toBe(true);
    expect(canRequestCollectionItem({ provider_key: "imdb", provider_id: "tt12", media_type: "movie" })).toBe(false);
  });

  it("summarizes collection properties without inventing empty markers", () => {
    const markers = collectionMarkers({
      id: "1",
      name: "Estive",
      enabled: true,
      server_ids: ["green", "purple"],
      season_start: "06-01",
      auto_enabled: true,
      auto_frequency: 80,
      refresh_metadata: true,
    });
    expect(markers).toEqual([
      { kind: "servers", label: "2 server" },
      { kind: "season", label: "Stagionale" },
      { kind: "automation", label: "Auto 80%" },
      { kind: "metadata", label: "Metadata" },
    ]);
    expect(collectionMarkers({ id: "2", name: "Manuale", enabled: true })).toEqual([]);
  });

  it("uses an explicit image URL only when the collection has one", () => {
    expect(
      collectionPosterUrl({ id: "1", name: "Senza immagine", enabled: true }),
    ).toBe("");
    expect(
      collectionPosterUrl({
        id: "2",
        name: "Con immagini",
        enabled: true,
        poster_url: "https://images.example/poster.jpg",
        poster_blob_url: "/api/v1/emby/collections/2/poster",
      }),
    ).toBe("/api/v1/emby/collections/2/poster");
  });
});
