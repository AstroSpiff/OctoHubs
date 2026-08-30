import type { EmbyCollection, CollectionSyncStatus, CollectionsFilters } from "@/features/collections/types";
import type { Severity } from "@/components/ui/badge";

export type CollectionMarker = {
  kind: "servers" | "season" | "automation" | "metadata";
  label: string;
};

const syncLabels: Record<CollectionSyncStatus, string> = {
  success: "Sincronizzata",
  partial: "Parziale",
  warning: "Da verificare",
  error: "Errore",
  empty: "Senza elementi",
  "": "Mai sincronizzata",
};

export const defaultCollectionsFilters: CollectionsFilters = {
  search: "",
  status: "all",
  sort: "name",
};

export function collectionSyncLabel(status?: CollectionSyncStatus | null): string {
  return syncLabels[status || ""];
}

export function collectionSyncSeverity(status?: CollectionSyncStatus | null): Severity {
  if (status === "success") return "ok";
  if (status === "partial" || status === "warning" || status === "empty") return "warning";
  if (status === "error") return "error";
  if (!status) return "neutral";
  return "unknown";
}

export function formatCollectionDate(value?: string | null): string {
  if (!value) return "Mai";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Non disponibile";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function visibleCollections(collections: EmbyCollection[], filters: CollectionsFilters): EmbyCollection[] {
  const search = filters.search.trim().toLocaleLowerCase("it-IT");
  const filtered = collections.filter((collection) => {
    const matchesSearch = !search || [
      collection.name,
      collection.source_display,
      collection.source_label,
      collection.server_display,
    ].some((value) => value?.toLocaleLowerCase("it-IT").includes(search));
    if (!matchesSearch) return false;
    if (filters.status === "enabled") return collection.enabled;
    if (filters.status === "disabled") return !collection.enabled;
    if (filters.status === "attention") return ["error", "partial", "warning", "empty"].includes(collection.last_sync_status || "");
    return true;
  });

  return [...filtered].sort((left, right) => {
    if (filters.sort === "sync") return String(right.last_sync_at || "").localeCompare(String(left.last_sync_at || ""));
    if (filters.sort === "source") return String(left.source_label || "").localeCompare(String(right.source_label || ""), "it");
    return left.name.localeCompare(right.name, "it");
  });
}

export function collectionCounts(collections: EmbyCollection[]) {
  return {
    total: collections.length,
    enabled: collections.filter((collection) => collection.enabled).length,
    attention: collections.filter((collection) => ["error", "partial", "warning", "empty"].includes(collection.last_sync_status || "")).length,
    automated: collections.filter((collection) => collection.auto_enabled).length,
  };
}

export function collectionMarkers(collection: EmbyCollection): CollectionMarker[] {
  const markers: CollectionMarker[] = [];
  const serverCount = collection.server_ids?.length || 0;
  if (serverCount) markers.push({ kind: "servers", label: `${serverCount} server` });
  if (collection.season_start || collection.season_end) markers.push({ kind: "season", label: "Stagionale" });
  if (collection.auto_enabled) markers.push({ kind: "automation", label: `Auto ${collection.auto_frequency ?? 100}%` });
  if (collection.refresh_metadata) markers.push({ kind: "metadata", label: "Metadata" });
  return markers;
}

export function collectionPosterUrl(collection: EmbyCollection): string {
  return collection.poster_blob_url || collection.poster_url || "";
}

export function collectionItemTmdbId(item: { tmdb_id?: string | number; provider_key?: string; provider_id?: string }): string {
  const value = item.tmdb_id || (item.provider_key === "tmdb" ? item.provider_id : "");
  return value ? String(value) : "";
}

export function canRequestCollectionItem(item: { tmdb_id?: string | number; provider_key?: string; provider_id?: string; media_type?: string }): boolean {
  return Boolean(collectionItemTmdbId(item) && item.media_type);
}
