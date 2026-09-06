import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteCollection, deleteCollectionImage, getCollectionOptions, getCollections, saveCollection, setCollectionEnabled, syncAllCollections, syncCollection, uploadCollectionImage } from "@/features/collections/api";
import {
  collectionRealtimeTargets,
  isCollectionsRealtimeEvent,
} from "@/features/collections/collections-realtime";
import { useCollectionOperationWatch } from "@/features/collections/use-collection-operation-watch";
import { useApplicationEventRefresh } from "@/lib/use-application-event";
import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";

function collectionActionKey(collectionId: string) {
  return `collection:${collectionId}`;
}

function useCollections() {
  const client = useQueryClient();
  const collections = useQuery({
    queryKey: ["collections"],
    queryFn: getCollections,
    refetchInterval: 15_000,
  });
  const options = useQuery({ queryKey: ["collection-options"], queryFn: getCollectionOptions, staleTime: 5 * 60_000 });
  const refresh = useCallback(
    () => client.invalidateQueries({ queryKey: ["collections"] }),
    [client],
  );
  const refreshFromRealtime = useCallback(
    (event: Parameters<typeof collectionRealtimeTargets>[0]) => {
      collectionRealtimeTargets(event).forEach((target) => {
        const queryKey =
          target === "collections"
            ? ["collections"]
            : target === "options"
              ? ["collection-options"]
              : ["collection-source-inventory"];
        void client.invalidateQueries({ queryKey });
      });
    },
    [client],
  );
  useApplicationEventRefresh(isCollectionsRealtimeEvent, refreshFromRealtime);
  const collectionOperations = useCollectionOperationWatch(() => {
    void refresh();
  });
  const toggleOperations = useKeyedOperationState();
  const syncOperations = useKeyedOperationState();
  const removeOperations = useKeyedOperationState();
  const toggle = useMutation({
    mutationFn: ({ collectionId, enabled }: { collectionId: string; enabled: boolean }) => setCollectionEnabled(collectionId, enabled),
    onMutate: ({ collectionId }) => toggleOperations.begin([collectionActionKey(collectionId)]),
    onError: (error, { collectionId }) => toggleOperations.fail([collectionActionKey(collectionId)], error),
    onSuccess: refresh,
    onSettled: (_data, _error, { collectionId }) => toggleOperations.finish([collectionActionKey(collectionId)]),
  });
  const sync = useMutation({
    mutationFn: syncCollection,
    onMutate: (collectionId) => syncOperations.begin([collectionActionKey(collectionId)]),
    onError: (error, collectionId) => syncOperations.fail([collectionActionKey(collectionId)], error),
    onSuccess: (result, collectionId) => {
      collectionOperations.track(result.operation_id, {
        type: "collection",
        collectionId,
      });
      void refresh();
    },
    onSettled: (_data, _error, collectionId) => syncOperations.finish([collectionActionKey(collectionId)]),
  });
  const syncAll = useMutation({
    mutationFn: syncAllCollections,
    onSuccess: (result) => {
      collectionOperations.track(result.operation_id, { type: "all" });
      void refresh();
    },
  });
  const save = useMutation({ mutationFn: saveCollection, onSuccess: refresh });
  const remove = useMutation({
    mutationFn: deleteCollection,
    onMutate: (collectionId) => removeOperations.begin([collectionActionKey(collectionId)]),
    onError: (error, collectionId) => removeOperations.fail([collectionActionKey(collectionId)], error),
    onSuccess: refresh,
    onSettled: (_data, _error, collectionId) => removeOperations.finish([collectionActionKey(collectionId)]),
  });
  const image = useMutation({ mutationFn: uploadCollectionImage, onSuccess: refresh });
  const removeImage = useMutation({ mutationFn: deleteCollectionImage, onSuccess: refresh });

  return {
    collections,
    options,
    toggle,
    toggleOperations,
    sync,
    syncOperations,
    syncAll,
    save,
    remove,
    removeOperations,
    image,
    removeImage,
    refresh,
    isSyncingAll: collectionOperations.isSyncingAll,
    isSyncingCollection: collectionOperations.isSyncingCollection,
  };
}

export { collectionActionKey, useCollections };
