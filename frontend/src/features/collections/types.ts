export type CollectionSyncStatus = "success" | "partial" | "warning" | "error" | "empty" | "";

export type EmbyCollection = {
  id: string;
  name: string;
  sort_name?: string;
  enabled: boolean;
  delete_pending?: boolean;
  source_type?: string;
  source_value?: string;
  source_label?: string;
  source_display?: string;
  source_link?: string;
  server_ids?: string[];
  server_labels?: string[];
  server_display?: string;
  servers?: CollectionServer[];
  poster_url?: string;
  last_sync_at?: string | null;
  last_sync_status?: CollectionSyncStatus | null;
  last_sync_message?: string | null;
  last_sync_items?: number | null;
  last_sync_candidates?: number | null;
  last_sync_per_server?: CollectionSyncDetail[];
  auto_enabled?: boolean;
  auto_frequency?: number;
  collection_description?: string;
  collection_sort_name?: string;
  use_source_description?: boolean;
  background_url?: string;
  background_blob_url?: string;
  poster_blob_url?: string;
  poster_uploaded?: boolean;
  background_uploaded?: boolean;
  season_start?: string;
  season_end?: string;
  refresh_metadata?: boolean;
  source_origin?: string;
};

export type CollectionsPayload = {
  success: boolean;
  collections: EmbyCollection[];
};

export type CollectionAction = {
  success: boolean;
  message?: string;
  operation_id?: string;
  collection?: EmbyCollection;
};

export type CollectionsFilters = {
  search: string;
  status: "all" | "enabled" | "disabled" | "attention";
  sort: "name" | "sync" | "source";
};

export type CollectionSourceType = {
  value: string;
  label: string;
  description?: string;
  placeholder?: string;
  help?: string;
};

export type CollectionServer = {
  id: string;
  name: string;
  icon?: string;
  icon_color?: string;
  icon_style?: string;
};

export type CollectionOptions = {
  success: boolean;
  source_types: CollectionSourceType[];
  servers: CollectionServer[];
  trakt_enabled: boolean;
  mdblist_enabled: boolean;
};

export type CollectionEditorInput = {
  id?: string;
  name: string;
  sort_name: string;
  source_type: string;
  source_value: string;
  source_origin?: string;
  server_ids: string[];
  poster_url?: string;
  background_url?: string;
  season_start?: string;
  season_end?: string;
  refresh_metadata: boolean;
  collection_description?: string;
  collection_sort_name?: string;
  use_source_description: boolean;
  enabled: boolean;
  auto_enabled: boolean;
  auto_frequency: number;
};

export type CollectionSyncDetail = {
  server_id?: string;
  server_label?: string;
  synced_at?: string | null;
  matched?: number;
  candidates?: number;
  missing?: number;
  message?: string;
  items?: CollectionSyncItem[];
};

export type CollectionSyncItem = {
  title?: string;
  year?: number | string;
  provider_key?: string;
  provider_label?: string;
  provider_id?: string;
  tmdb_id?: string | number;
  media_type?: string;
  found?: boolean;
};

export type CollectionSourceInventoryItem = {
  id: string;
  name: string;
  source_type: string;
  source_value: string;
  source_link?: string;
  origin?: string;
};

export type CollectionSourceInventoryInput = Pick<
  CollectionSourceInventoryItem,
  "source_type" | "source_value"
> & {
  name?: string;
};

export type PersonalCollectionList = {
  name?: string;
  title?: string;
  description?: string;
  source_type?: string;
  source_value?: string;
  value?: string;
  url?: string;
  link?: string;
  item_count?: number;
  count?: number;
};
