import { useMemo, useRef, useState } from "react";

import { CollectionEditorDialog } from "@/features/collections/components/collection-editor-dialog";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { CollectionsList } from "@/features/collections/components/collections-list";
import { CollectionsOverview } from "@/features/collections/components/collections-overview";
import { CollectionsPageHeader } from "@/features/collections/components/collections-page-header";
import { CollectionSourcesDialog } from "@/features/collections/components/collection-sources-dialog";
import {
  saveCollectionWithImages,
  type CompletedCollectionImageUploads,
} from "@/features/collections/collection-save-flow";
import type { SourceSelection } from "@/features/collections/collection-source-selection";
import { CollectionSyncDetailsDialog } from "@/features/collections/components/collection-sync-details-dialog";
import { CollectionsToolbar } from "@/features/collections/components/collections-toolbar";
import { defaultCollectionsFilters, visibleCollections } from "@/features/collections/presentation";
import type { CollectionEditorInput, CollectionsFilters, EmbyCollection } from "@/features/collections/types";
import { collectionActionKey, useCollections } from "@/features/collections/use-collections";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";

function CollectionsPage() {
  const [filters, setFilters] = useState<CollectionsFilters>(defaultCollectionsFilters);
  const confirmation = useConfirmationDialog();
  const [editorCollection, setEditorCollection] = useState<EmbyCollection | null | undefined>(undefined);
  const [detailsCollection, setDetailsCollection] = useState<EmbyCollection | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [sourceSelection, setSourceSelection] = useState<SourceSelection | null>(null);
  const [editorDirty, setEditorDirty] = useState(false);
  const [sourcesDirty, setSourcesDirty] = useState(false);
  const completedImageUploads = useRef<CompletedCollectionImageUploads>({});
  const collections = useCollections();
  const hasUnsavedChanges = editorDirty || sourcesDirty;
  useBeforeUnloadWarning(hasUnsavedChanges);
  useUnsavedChangesNavigationGuard(hasUnsavedChanges, confirmation.confirm);
  const data = useMemo(() => collections.collections.data?.collections || [], [collections.collections.data]);
  const visible = useMemo(() => visibleCollections(data, filters), [data, filters]);
  const syncingAll = collections.syncAll.isPending || collections.isSyncingAll;
  const error = collections.options.error || collections.syncAll.error || collections.save.error || collections.image.error || collections.removeImage.error;

  function isChangingCollection(collectionId: string) {
    const key = collectionActionKey(collectionId);
    return collections.toggleOperations.pendingKeys.has(key)
      || collections.syncOperations.pendingKeys.has(key)
      || collections.removeOperations.pendingKeys.has(key);
  }

  function isSyncingCollection(collectionId: string) {
    return collections.isSyncingCollection(collectionId)
      || collections.syncOperations.pendingKeys.has(collectionActionKey(collectionId));
  }

  function collectionActionError(collectionId: string) {
    const key = collectionActionKey(collectionId);
    return collections.toggleOperations.errors[key]
      || collections.syncOperations.errors[key]
      || collections.removeOperations.errors[key];
  }

  function updateFilters(changes: Partial<CollectionsFilters>) {
    setFilters((current) => ({ ...current, ...changes }));
  }

  function toggle(collection: EmbyCollection) {
    collections.toggle.mutate({ collectionId: collection.id, enabled: !collection.enabled });
  }

  function sync(collection: EmbyCollection) {
    collections.sync.mutate(collection.id);
  }

  async function save(input: CollectionEditorInput, files: { poster?: File; backdrop?: File }) {
    await saveCollectionWithImages({
      input,
      files,
      completedUploads: completedImageUploads.current,
      save: collections.save.mutateAsync,
      upload: collections.image.mutateAsync,
      // Promote the editor as soon as the core save succeeds. A retry then
      // updates this id and the editor keeps any image File still pending.
      onCollectionSaved: setEditorCollection,
    });
  }

  async function removeImage(collectionId: string, kind: "poster" | "backdrop") {
    await collections.removeImage.mutateAsync({ collectionId, kind });
  }

  async function remove(collection: EmbyCollection) {
    if (!await confirmation.confirm({
      title: "Elimina collezione",
      description: `Eliminare la collezione ${collection.name}? Verrà rimossa anche dai server Emby selezionati.`,
      confirmLabel: "Elimina collezione",
      tone: "danger",
    })) return;
    collections.remove.mutate(collection.id);
  }

  async function syncAll() {
    if (!await confirmation.confirm({
      title: "Sincronizza tutte le collezioni",
      description:
        "Le collezioni disabilitate o segnate per la rimozione verranno eliminate anche dai server Emby. Continuare?",
      confirmLabel: "Sincronizza tutte",
      tone: "danger",
    })) return;
    collections.syncAll.mutate();
  }

  function chooseSource(selection: SourceSelection) {
    setSourceSelection(selection);
    if (editorCollection === undefined) setEditorCollection(null);
  }

  return (
    <WorkspacePage>
      <CollectionsPageHeader
        optionsLoading={collections.options.isLoading}
        refreshing={collections.collections.isFetching}
        syncing={syncingAll}
        onOpenSources={() => setSourcesOpen(true)}
        onRefresh={() => void collections.collections.refetch()}
        onCreate={() => setEditorCollection(null)}
        onSyncAll={() => void syncAll()}
      />

      {error ? <div className="inline-alert inline-alert--error" role="alert">{error.message}</div> : null}
      {collections.syncAll.isSuccess ? <div className="inline-alert inline-alert--success" role="status">Sincronizzazione globale avviata. Lo stato si aggiorna automaticamente.</div> : null}
      <QueryStateBoundary
        error={collections.collections.error}
        hasData={Boolean(collections.collections.data)}
        loadingLabel="Caricamento collezioni..."
        retrying={collections.collections.isFetching}
        onRetry={() => void collections.collections.refetch()}
      >
        <CollectionsOverview collections={data} />
        <CollectionsToolbar filters={filters} onChange={updateFilters} />
        <CollectionsList
          collections={visible}
          syncingAll={syncingAll}
          isChangingCollection={isChangingCollection}
          isSyncingCollection={isSyncingCollection}
          collectionActionError={collectionActionError}
          onToggle={toggle}
          onSync={sync}
          onEdit={setEditorCollection}
          onDetails={setDetailsCollection}
          onDelete={remove}
          onCreate={() => setEditorCollection(null)}
        />
      </QueryStateBoundary>

      <CollectionEditorDialog
        collection={editorCollection}
        options={collections.options.data}
        saving={collections.save.isPending || collections.image.isPending || collections.removeImage.isPending}
        sourceSelection={sourceSelection}
        sourcesDirty={sourcesDirty}
        sourcesOpen={sourcesOpen}
        onClose={() => { setEditorCollection(undefined); setSourceSelection(null); setSourcesOpen(false); }}
        onDirtyChange={setEditorDirty}
        onSourcesDirtyChange={setSourcesDirty}
        onOpenSources={() => setSourcesOpen(true)}
        onCloseSources={() => setSourcesOpen(false)}
        onSelectSource={(selection) => { chooseSource(selection); setSourcesOpen(false); }}
        onSave={save}
        onRemoveImage={removeImage}
      />
      <CollectionSourcesDialog open={sourcesOpen && editorCollection === undefined} options={collections.options.data} onClose={() => setSourcesOpen(false)} onSelect={chooseSource} onDirtyChange={setSourcesDirty} />
      <CollectionSyncDetailsDialog collection={detailsCollection} onClose={() => setDetailsCollection(null)} />
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { CollectionsPage };
