import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteCollection, deleteCollectionImage, getCollectionOptions, getCollections, saveCollection, setCollectionEnabled, syncAllCollections, syncCollection, uploadCollectionImage } from "@/features/collections/api";
import {
  collectionRealtimeTargets,
  isCollectionsRealtimeEvent,
} from "@/features/collections/collections-realtime";
import { useCollectionOperationWatch } from "@/features/collections/use-collection-operation-watch";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

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
  const toggle = useMutation({
    mutationFn: ({ collectionId, enabled }: { collectionId: string; enabled: boolean }) => setCollectionEnabled(collectionId, enabled),
    onSuccess: refresh,
  });
  const sync = useMutation({
    mutationFn: syncCollection,
    onSuccess: (result, collectionId) => {
      collectionOperations.track(result.operation_id, {
        type: "collection",
        collectionId,
      });
      void refresh();
    },
  });
  const syncAll = useMutation({
    mutationFn: syncAllCollections,
    onSuccess: (result) => {
      collectionOperations.track(result.operation_id, { type: "all" });
      void refresh();
    },
  });
  const save = useMutation({ mutationFn: saveCollection, onSuccess: refresh });
  const remove = useMutation({ mutationFn: deleteCollection, onSuccess: refresh });
  const image = useMutation({ mutationFn: uploadCollectionImage, onSuccess: refresh });
  const removeImage = useMutation({ mutationFn: deleteCollectionImage, onSuccess: refresh });

  return {
    collections,
    options,
    toggle,
    sync,
    syncAll,
    save,
    remove,
    image,
    removeImage,
    refresh,
    isSyncingAll: collectionOperations.isSyncingAll,
    isSyncingCollection: collectionOperations.isSyncingCollection,
  };
}

export { useCollections };
