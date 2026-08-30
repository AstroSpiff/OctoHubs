import { useMemo, useState } from "react";

import { CollectionEditorDialog } from "@/features/collections/components/collection-editor-dialog";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { CollectionsList } from "@/features/collections/components/collections-list";
import { CollectionsOverview } from "@/features/collections/components/collections-overview";
import { CollectionsPageHeader } from "@/features/collections/components/collections-page-header";
import { CollectionSourcesDialog } from "@/features/collections/components/collection-sources-dialog";
import type { SourceSelection } from "@/features/collections/collection-source-selection";
import { CollectionSyncDetailsDialog } from "@/features/collections/components/collection-sync-details-dialog";
import { CollectionsToolbar } from "@/features/collections/components/collections-toolbar";
import { defaultCollectionsFilters, visibleCollections } from "@/features/collections/presentation";
import type { CollectionEditorInput, CollectionsFilters, EmbyCollection } from "@/features/collections/types";
import { useCollections } from "@/features/collections/use-collections";
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
  const collections = useCollections();
  const hasUnsavedChanges = editorDirty || sourcesDirty;
  useBeforeUnloadWarning(hasUnsavedChanges);
  useUnsavedChangesNavigationGuard(hasUnsavedChanges, confirmation.confirm);
  const data = useMemo(() => collections.collections.data?.collections || [], [collections.collections.data]);
  const visible = useMemo(() => visibleCollections(data, filters), [data, filters]);
  const syncingAll = collections.syncAll.isPending || collections.isSyncingAll;
  const error = collections.collections.error || collections.options.error || collections.toggle.error || collections.sync.error || collections.syncAll.error || collections.save.error || collections.remove.error || collections.image.error || collections.removeImage.error;
  const changingId = collections.toggle.isPending
    ? collections.toggle.variables?.collectionId
    : undefined;

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
    const result = await collections.save.mutateAsync(input);
    const collectionId = result.collection.id;
    // If a later image upload fails, a retry must update this collection rather
    // than create a second one from the still-open "new collection" editor.
    setEditorCollection(result.collection);
    if (files.poster) await collections.image.mutateAsync({ collectionId, kind: "poster", file: files.poster });
    if (files.backdrop) await collections.image.mutateAsync({ collectionId, kind: "backdrop", file: files.backdrop });
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
      {collections.collections.isLoading ? <div className="loading-state">Caricamento collezioni...</div> : null}

      <CollectionsOverview collections={data} />
      <CollectionsToolbar filters={filters} onChange={updateFilters} />
      <CollectionsList
        collections={visible}
        changingId={changingId}
        syncingAll={syncingAll}
        isSyncingCollection={collections.isSyncingCollection}
        onToggle={toggle}
        onSync={sync}
        onEdit={setEditorCollection}
        onDetails={setDetailsCollection}
        onDelete={remove}
        onCreate={() => setEditorCollection(null)}
      />

      <CollectionEditorDialog
        collection={editorCollection}
        options={collections.options.data}
        saving={collections.save.isPending || collections.image.isPending || collections.removeImage.isPending}
        sourceSelection={sourceSelection}
        onClose={() => { setEditorCollection(undefined); setSourceSelection(null); }}
        onDirtyChange={setEditorDirty}
        onSourcesDirtyChange={setSourcesDirty}
        onOpenSources={() => setSourcesOpen(true)}
        onSelectSource={chooseSource}
        onSave={save}
        onRemoveImage={removeImage}
      />
      <CollectionSourcesDialog open={sourcesOpen} options={collections.options.data} onClose={() => setSourcesOpen(false)} onSelect={chooseSource} onDirtyChange={setSourcesDirty} />
      <CollectionSyncDetailsDialog collection={detailsCollection} onClose={() => setDetailsCollection(null)} />
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { CollectionsPage };
