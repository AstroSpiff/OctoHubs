import type {
  CollectionEditorInput,
  CollectionOptions,
  EmbyCollection,
} from "@/features/collections/types";

type CollectionEditorState = Omit<CollectionEditorInput, "id"> & {
  poster?: File;
  backdrop?: File;
};

const emptyCollectionEditorState: CollectionEditorState = {
  name: "",
  sort_name: "",
  source_type: "",
  source_value: "",
  source_origin: "manual",
  server_ids: [],
  poster_url: "",
  background_url: "",
  season_start: "",
  season_end: "",
  refresh_metadata: false,
  collection_description: "",
  collection_sort_name: "",
  use_source_description: false,
  enabled: true,
  auto_enabled: false,
  auto_frequency: 100,
};

const collectionEditorComparableKeys = [
  "name",
  "sort_name",
  "source_type",
  "source_value",
  "source_origin",
  "poster_url",
  "background_url",
  "season_start",
  "season_end",
  "refresh_metadata",
  "collection_description",
  "collection_sort_name",
  "use_source_description",
  "enabled",
  "auto_enabled",
  "auto_frequency",
] as const satisfies ReadonlyArray<keyof CollectionEditorState>;

function collectionEditorState(
  collection: EmbyCollection | null,
  options: CollectionOptions | undefined,
): CollectionEditorState {
  const sourceType =
    collection?.source_type || options?.source_types[0]?.value || "";

  if (!collection) {
    return {
      ...emptyCollectionEditorState,
      source_type: sourceType,
      server_ids: options?.servers.map((server) => server.id) || [],
    };
  }

  return {
    ...emptyCollectionEditorState,
    name: collection.name,
    sort_name: collection.sort_name || collection.name,
    source_type: sourceType,
    source_value: collection.source_value || "",
    source_origin: collection.source_origin || "manual",
    server_ids: [...(collection.server_ids || [])],
    poster_url: collection.poster_url || "",
    background_url: collection.background_url || "",
    season_start: collection.season_start || "",
    season_end: collection.season_end || "",
    refresh_metadata: collection.refresh_metadata === true,
    collection_description: collection.collection_description || "",
    collection_sort_name:
      collection.collection_sort_name || collection.sort_name || collection.name,
    use_source_description: collection.use_source_description === true,
    enabled: collection.enabled,
    auto_enabled: collection.auto_enabled === true,
    auto_frequency: collection.auto_frequency ?? 100,
  };
}

function collectionEditorStateMatches(
  first: CollectionEditorState,
  second: CollectionEditorState,
): boolean {
  if (
    first.server_ids.length !== second.server_ids.length ||
    first.server_ids.some((serverId) => !second.server_ids.includes(serverId))
  ) {
    return false;
  }

  if (first.poster !== second.poster || first.backdrop !== second.backdrop) {
    return false;
  }

  return collectionEditorComparableKeys.every(
    (key) => first[key] === second[key],
  );
}

function shouldRefreshCollectionEditorDraft(
  draft: CollectionEditorState,
  baseline: CollectionEditorState,
  previousCollectionKey: string | null,
  nextCollectionKey: string,
): boolean {
  return (
    previousCollectionKey !== nextCollectionKey ||
    collectionEditorStateMatches(draft, baseline)
  );
}

export {
  collectionEditorState,
  collectionEditorStateMatches,
  emptyCollectionEditorState,
  shouldRefreshCollectionEditorDraft,
  type CollectionEditorState,
};
