import { request } from "@/lib/http";
import { getOperations } from "@/features/operations/api";
import { isActiveOperation } from "@/features/operations/presentation";
import type { Operation } from "@/features/operations/types";
import type { CollectionAction, CollectionEditorInput, CollectionOptions, CollectionSourceInventoryInput, CollectionSourceInventoryItem, CollectionSyncDetail, CollectionsPayload, PersonalCollectionList } from "@/features/collections/types";

export function getCollections(): Promise<CollectionsPayload> {
  return request<CollectionsPayload>("/api/v1/emby/collections");
}

export function getCollectionOptions(): Promise<CollectionOptions> {
  return request<CollectionOptions>("/api/v1/emby/collections/options");
}

export function saveCollection(input: CollectionEditorInput): Promise<{ success: boolean; collection: import("@/features/collections/types").EmbyCollection }> {
  return request<{ success: boolean; collection: import("@/features/collections/types").EmbyCollection }>("/api/v1/emby/collections", { method: "POST", body: JSON.stringify(input) });
}

export function deleteCollection(collectionId: string): Promise<CollectionAction> {
  return request<CollectionAction>(`/api/v1/emby/collections/${encodeURIComponent(collectionId)}/delete`, { method: "POST", body: JSON.stringify({}) });
}

export function uploadCollectionImage({ collectionId, kind, file }: { collectionId: string; kind: "poster" | "backdrop"; file: File }): Promise<{ success: boolean }> {
  const body = new FormData();
  body.set("file", file);
  return request<{ success: boolean }>(`/api/v1/emby/collections/${encodeURIComponent(collectionId)}/${kind}`, { method: "POST", body });
}

export function deleteCollectionImage({ collectionId, kind }: { collectionId: string; kind: "poster" | "backdrop" }): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(`/api/v1/emby/collections/${encodeURIComponent(collectionId)}/${kind}/delete`, { method: "POST", body: JSON.stringify({}) });
}

export function getCollectionSyncDetails(collectionId: string): Promise<{ success: boolean; details: CollectionSyncDetail[] }> {
  return request<{ success: boolean; details: CollectionSyncDetail[] }>(`/api/v1/emby/collections/${encodeURIComponent(collectionId)}/sync-details`);
}

type CollectionListResponse = {
  success: boolean;
  lists?: PersonalCollectionList[];
  background?: boolean;
  operation_id?: string;
};

export async function getTraktLists(): Promise<{ success: boolean; lists: PersonalCollectionList[] }> {
  const response = await request<CollectionListResponse>("/api/v1/emby/collections/trakt-lists?background=1");
  return waitForCollectionLists(response, "Trakt");
}

export async function getMdbListLists(): Promise<{ success: boolean; lists: PersonalCollectionList[] }> {
  const response = await request<CollectionListResponse>("/api/v1/emby/collections/mdblist-lists?background=1");
  return waitForCollectionLists(response, "MDBList");
}

async function waitForCollectionLists(
  response: CollectionListResponse,
  label: string,
): Promise<{ success: boolean; lists: PersonalCollectionList[] }> {
  if (!response.background) return { success: response.success, lists: response.lists || [] };
  if (!response.operation_id) throw new Error(`Operazione ${label} non disponibile.`);
  return collectionListsFromOperation(
    await waitForCollectionOperation(response.operation_id),
    label,
  );
}

async function waitForCollectionOperation(operationId: string): Promise<Operation> {
  const timeoutAt = Date.now() + 240_000;
  while (Date.now() < timeoutAt) {
    const snapshot = await getOperations();
    const operation = snapshot.operations.find((item) => item.id === operationId);
    if (operation && !isActiveOperation(operation)) return operation;
    await new Promise<void>((resolve) => window.setTimeout(resolve, 1_500));
  }
  throw new Error("Tempo massimo di attesa dell'operazione superato.");
}

export function collectionListsFromOperation(
  operation: Operation,
  label: string,
): { success: boolean; lists: PersonalCollectionList[] } {
  if (operation.status !== "success") {
    throw new Error(operation.error || operation.message || `Aggiornamento ${label} non riuscito.`);
  }
  return {
    success: true,
    lists: Array.isArray(operation.result?.lists)
      ? (operation.result.lists as PersonalCollectionList[])
      : [],
  };
}

export function getCollectionSourceInventory(): Promise<{ success: boolean; items: CollectionSourceInventoryItem[] }> {
  return request<{ success: boolean; items: CollectionSourceInventoryItem[] }>("/api/v1/emby/collections/source-inventory");
}

export function saveCollectionSourceInventory(input: CollectionSourceInventoryInput): Promise<{ success: boolean; item: CollectionSourceInventoryItem; items: CollectionSourceInventoryItem[] }> {
  return request<{ success: boolean; item: CollectionSourceInventoryItem; items: CollectionSourceInventoryItem[] }>("/api/v1/emby/collections/source-inventory", { method: "POST", body: JSON.stringify(input) });
}

export function deleteCollectionSourceInventory(itemId: string): Promise<{ success: boolean; items: CollectionSourceInventoryItem[] }> {
  return request<{ success: boolean; items: CollectionSourceInventoryItem[] }>(`/api/v1/emby/collections/source-inventory/${encodeURIComponent(itemId)}/delete`, { method: "POST", body: JSON.stringify({}) });
}

export function setCollectionEnabled(collectionId: string, enabled: boolean): Promise<CollectionAction> {
  return request<CollectionAction>(`/api/v1/emby/collections/${encodeURIComponent(collectionId)}/toggle`, {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

export function syncCollection(collectionId: string): Promise<CollectionAction> {
  return request<CollectionAction>(`/api/v1/emby/collections/${encodeURIComponent(collectionId)}/sync?background=1`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function syncAllCollections(): Promise<CollectionAction> {
  return request<CollectionAction>("/api/v1/emby/collections/sync-all?background=1", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function requestCollectionItemFromJellyseerr(item: { tmdb_id?: string | number; provider_key?: string; provider_id?: string; media_type?: string }): Promise<{ success: boolean; message?: string; error?: string }> {
  const tmdbId = item.tmdb_id || (item.provider_key === "tmdb" ? item.provider_id : undefined);
  if (!tmdbId || !item.media_type) throw new Error("TMDB ID o tipo media non disponibili per questo elemento.");
  const result = await request<{ success: boolean; message?: string; error?: string }>("/api/v1/research/requests/create", {
    method: "POST",
    body: JSON.stringify({ mediaId: Number(tmdbId), mediaType: item.media_type }),
  });
  if (!result.success) throw new Error(result.message || result.error || "Richiesta Jellyseerr non riuscita.");
  return result;
}
