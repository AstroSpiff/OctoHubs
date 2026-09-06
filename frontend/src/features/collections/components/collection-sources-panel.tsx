import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { CollectionSourceInventorySection } from "@/features/collections/components/collection-source-inventory-section";
import { CollectionSourceRemoteSection } from "@/features/collections/components/collection-source-remote-section";
import {
  deleteCollectionSourceInventory,
  getCollectionSourceInventory,
  getMdbListLists,
  getTraktLists,
  saveCollectionSourceInventory,
} from "@/features/collections/api";
import type { SourceSelection } from "@/features/collections/collection-source-selection";
import type {
  CollectionOptions,
  CollectionSourceInventoryInput,
  CollectionSourceInventoryItem,
} from "@/features/collections/types";

type CollectionSourcesPanelProps = {
  enabled: boolean;
  disabled?: boolean;
  options?: CollectionOptions;
  onSelect: (selection: SourceSelection) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onBusyChange?: (busy: boolean) => void;
};

function CollectionSourcesPanel({
  enabled,
  disabled = false,
  options,
  onSelect,
  onDirtyChange,
  onBusyChange,
}: CollectionSourcesPanelProps) {
  const confirmation = useConfirmationDialog();
  const client = useQueryClient();
  const inventory = useQuery({
    queryKey: ["collection-source-inventory"],
    queryFn: getCollectionSourceInventory,
    enabled,
  });
  const trakt = useQuery({
    queryKey: ["collection-trakt-lists"],
    queryFn: ({ signal }) => getTraktLists(signal),
    enabled: enabled && options?.trakt_enabled === true,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
  const mdblist = useQuery({
    queryKey: ["collection-mdblist-lists"],
    queryFn: ({ signal }) => getMdbListLists(signal),
    enabled: enabled && options?.mdblist_enabled === true,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [inventoryDirty, setInventoryDirty] = useState(false);

  useEffect(() => {
    onDirtyChange?.(enabled && inventoryDirty);
    return () => onDirtyChange?.(false);
  }, [enabled, inventoryDirty, onDirtyChange]);

  useEffect(() => {
    if (!enabled) setInventoryDirty(false);
  }, [enabled]);

  useEffect(() => {
    onBusyChange?.(enabled && busy);
  }, [busy, enabled, onBusyChange]);

  useEffect(
    () => () => onBusyChange?.(false),
    [onBusyChange],
  );

  async function addInventory(input: CollectionSourceInventoryInput) {
    if (disabled || busy) return;
    setBusy(true);
    setError("");
    try {
      await saveCollectionSourceInventory(input);
      await client.invalidateQueries({
        queryKey: ["collection-source-inventory"],
      });
    } finally {
      setBusy(false);
    }
  }

  async function removeInventory(item: CollectionSourceInventoryItem) {
    if (disabled || busy) return;
    if (
      !(await confirmation.confirm({
        title: "Elimina fonte salvata",
        description: `Eliminare la fonte salvata ${item.name}?`,
        confirmLabel: "Elimina fonte",
        tone: "danger",
      }))
    )
      return;
    setBusy(true);
    setError("");
    try {
      await deleteCollectionSourceInventory(item.id);
      await client.invalidateQueries({
        queryKey: ["collection-source-inventory"],
      });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Impossibile eliminare la fonte.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function choose(selection: SourceSelection) {
    if (disabled || busy) return;
    if (
      inventoryDirty &&
      !(await confirmation.confirm({
        title: "Fonte manuale non salvata",
        description: "Usare questa lista e perdere il riferimento manuale in corso?",
        confirmLabel: "Usa questa lista",
        tone: "danger",
      }))
    ) {
      return;
    }
    setInventoryDirty(false);
    onSelect(selection);
  }

  return (
    <>
      {error ? (
        <p className="users-dialog-error" role="alert">
          {error}
        </p>
      ) : null}
      <CollectionSourceInventorySection
        options={options}
        items={inventory.data?.items || []}
        refreshing={inventory.isFetching}
        error={inventory.error?.message}
        busy={disabled || busy}
        onRefresh={() => void inventory.refetch()}
        onAdd={addInventory}
        onChoose={(selection) => void choose(selection)}
        onDelete={removeInventory}
        onDirtyChange={setInventoryDirty}
      />
      <CollectionSourceRemoteSection
        title="Liste Trakt"
        defaultSourceType="trakt_list"
        unavailable={!options?.trakt_enabled}
        loading={trakt.isLoading}
        busy={disabled || busy}
        error={trakt.error?.message}
        items={trakt.data?.lists || []}
        onRefresh={() => void trakt.refetch()}
        onChoose={(selection) => void choose(selection)}
      />
      <CollectionSourceRemoteSection
        title="Liste MDBList"
        defaultSourceType="mdblist"
        unavailable={!options?.mdblist_enabled}
        loading={mdblist.isLoading}
        busy={disabled || busy}
        error={mdblist.error?.message}
        items={mdblist.data?.lists || []}
        onRefresh={() => void mdblist.refetch()}
        onChoose={(selection) => void choose(selection)}
      />
      {confirmation.dialog}
    </>
  );
}

export { CollectionSourcesPanel };
