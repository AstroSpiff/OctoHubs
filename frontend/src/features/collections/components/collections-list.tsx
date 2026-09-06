import { FolderPlus, FolderSearch2 } from "@/components/ui/icons";

import { CollectionCard } from "@/features/collections/components/collection-card";
import { WriteAction } from "@/features/session/workspace-capabilities";
import type { EmbyCollection } from "@/features/collections/types";

type CollectionsListProps = {
  collections: EmbyCollection[];
  syncingAll: boolean;
  isChangingCollection: (collectionId: string) => boolean;
  isSyncingCollection: (collectionId: string) => boolean;
  collectionActionError: (collectionId: string) => string | undefined;
  onToggle: (collection: EmbyCollection) => void;
  onSync: (collection: EmbyCollection) => void;
  onEdit: (collection: EmbyCollection) => void;
  onDetails: (collection: EmbyCollection) => void;
  onDelete: (collection: EmbyCollection) => void;
  onCreate: () => void;
};

function CollectionsList({ collections, syncingAll, isChangingCollection, isSyncingCollection, collectionActionError, onToggle, onSync, onEdit, onDetails, onDelete, onCreate }: CollectionsListProps) {
  return (
    <div className="collections-grid">
      <WriteAction>
        <button type="button" className="collection-create-card" onClick={onCreate}>
          <FolderPlus size={30} aria-hidden="true" />
          <span>Nuova collezione</span>
        </button>
      </WriteAction>
      {!collections.length ? <div className="collections-empty"><FolderSearch2 size={24} aria-hidden="true" /><div><strong>Nessuna collezione corrispondente</strong><p>Modifica i filtri oppure crea una nuova collezione.</p></div></div> : null}
      {collections.map((collection) => <CollectionCard key={collection.id} collection={collection} changing={isChangingCollection(collection.id)} syncing={syncingAll || isSyncingCollection(collection.id)} syncingAll={syncingAll} actionError={collectionActionError(collection.id)} onToggle={onToggle} onSync={onSync} onEdit={onEdit} onDetails={onDetails} onDelete={onDelete} />)}
    </div>
  );
}

export { CollectionsList };
