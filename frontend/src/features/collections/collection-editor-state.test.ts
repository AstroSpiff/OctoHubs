import { describe, expect, it } from "vitest";

import {
  collectionEditorState,
  collectionEditorStateMatches,
  promoteNewCollectionEditorDraft,
  shouldRefreshCollectionEditorDraft,
} from "@/features/collections/collection-editor-state";

describe("collectionEditorState", () => {
  it("starts a new collection with the first source and every configured server", () => {
    expect(
      collectionEditorState(null, {
        success: true,
        source_types: [{ value: "trakt", label: "Trakt" }],
        servers: [
          { id: "green", name: "Green" },
          { id: "purple", name: "Purple" },
        ],
        trakt_enabled: true,
        mdblist_enabled: true,
      }),
    ).toMatchObject({
      source_type: "trakt",
      server_ids: ["green", "purple"],
      enabled: true,
      auto_frequency: 100,
    });
  });

  it("restores the saved values of an existing collection without sharing its server list", () => {
    const source = {
      id: "collection-1",
      name: "Cinema",
      enabled: false,
      source_type: "mdblist",
      source_value: "lista",
      server_ids: ["green"],
      auto_frequency: 35,
    };

    const state = collectionEditorState(source, undefined);
    state.server_ids.push("purple");

    expect(state).toMatchObject({
      sort_name: "Cinema",
      collection_sort_name: "Cinema",
      enabled: false,
      auto_frequency: 35,
    });
    expect(source.server_ids).toEqual(["green"]);
  });

  it("compares editor drafts structurally, including media and selected servers", () => {
    const saved = collectionEditorState(null, {
      success: true,
      source_types: [{ value: "trakt", label: "Trakt" }],
      servers: [
        { id: "green", name: "Green" },
        { id: "purple", name: "Purple" },
      ],
      trakt_enabled: true,
      mdblist_enabled: true,
    });

    expect(
      collectionEditorStateMatches(saved, {
        ...saved,
        server_ids: ["purple", "green"],
      }),
    ).toBe(true);
    expect(
      collectionEditorStateMatches(saved, {
        ...saved,
        collection_description: "Descrizione aggiornata",
      }),
    ).toBe(false);
    expect(
      collectionEditorStateMatches(saved, {
        ...saved,
        poster: new File(["image"], "poster.png", { type: "image/png" }),
      }),
    ).toBe(false);
  });

  it("only refreshes the current editor when its local draft is clean", () => {
    const saved = collectionEditorState(null, {
      success: true,
      source_types: [{ value: "trakt", label: "Trakt" }],
      servers: [{ id: "green", name: "Green" }],
      trakt_enabled: true,
      mdblist_enabled: true,
    });
    const draft = { ...saved, name: "Bozza locale" };

    expect(
      shouldRefreshCollectionEditorDraft(saved, saved, "collection-1", "collection-1"),
    ).toBe(true);
    expect(
      shouldRefreshCollectionEditorDraft(draft, saved, "collection-1", "collection-1"),
    ).toBe(false);
    expect(
      shouldRefreshCollectionEditorDraft(draft, saved, "collection-1", "collection-2"),
    ).toBe(true);
  });

  it("preserves pending image files when a newly saved collection receives its id", () => {
    const saved = collectionEditorState(
      {
        id: "collection-1",
        name: "Cinema",
        enabled: true,
        source_type: "trakt",
        source_value: "cinema",
        server_ids: ["green"],
      },
      undefined,
    );
    const poster = new File(["poster"], "poster.png", { type: "image/png" });
    const backdrop = new File(["backdrop"], "backdrop.webp", {
      type: "image/webp",
    });

    const promoted = promoteNewCollectionEditorDraft(
      { ...saved, name: "Bozza prima del salvataggio", poster, backdrop },
      saved,
    );

    expect(promoted).toMatchObject({ name: "Cinema", poster, backdrop });
    expect(collectionEditorStateMatches(promoted, saved)).toBe(false);
  });
});
