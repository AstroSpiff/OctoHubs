import { ListPlus, RotateCcw } from "@/components/ui/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { CollectionEditorAutomationFields } from "@/features/collections/components/collection-editor-automation-fields";
import { CollectionEditorCoreFields } from "@/features/collections/components/collection-editor-core-fields";
import { CollectionEditorMediaFields } from "@/features/collections/components/collection-editor-media-fields";
import { CollectionSourcesPanel } from "@/features/collections/components/collection-sources-panel";
import type { SourceSelection } from "@/features/collections/collection-source-selection";
import {
  collectionEditorState,
  collectionEditorStateMatches,
  emptyCollectionEditorState,
  shouldRefreshCollectionEditorDraft,
  type CollectionEditorState,
} from "@/features/collections/collection-editor-state";
import type {
  CollectionEditorInput,
  CollectionOptions,
  EmbyCollection,
} from "@/features/collections/types";

type CollectionEditorDialogProps = {
  collection: EmbyCollection | null | undefined;
  options: CollectionOptions | undefined;
  saving: boolean;
  onClose: () => void;
  onOpenSources: () => void;
  onSelectSource: (selection: SourceSelection) => void;
  sourceSelection?: SourceSelection | null;
  onDirtyChange?: (dirty: boolean) => void;
  onSourcesDirtyChange?: (dirty: boolean) => void;
  onSave: (
    input: CollectionEditorInput,
    files: { poster?: File; backdrop?: File },
  ) => Promise<void>;
  onRemoveImage: (
    collectionId: string,
    kind: "poster" | "backdrop",
  ) => Promise<void>;
};

function CollectionEditorDialog({
  collection,
  options,
  saving,
  onClose,
  onOpenSources,
  onSelectSource,
  sourceSelection,
  onDirtyChange,
  onSourcesDirtyChange,
  onSave,
  onRemoveImage,
}: CollectionEditorDialogProps) {
  const confirmation = useConfirmationDialog();
  const [form, setForm] = useState<CollectionEditorState>(
    emptyCollectionEditorState,
  );
  const [baseline, setBaseline] = useState<CollectionEditorState>(
    emptyCollectionEditorState,
  );
  const [error, setError] = useState("");
  const [removing, setRemoving] = useState<"poster" | "backdrop" | null>(null);
  const [removedMedia, setRemovedMedia] = useState({
    poster: false,
    backdrop: false,
  });
  const formRef = useRef(form);
  const baselineRef = useRef(baseline);
  const collectionKeyRef = useRef<string | null>(null);
  const collectionKey =
    collection === undefined ? null : collection?.id || "__new_collection__";
  const savedForm = useMemo(
    () =>
      collection === undefined
        ? null
        : collectionEditorState(collection, options),
    [collection, options],
  );

  const replaceForm = useCallback((nextForm: CollectionEditorState) => {
    formRef.current = nextForm;
    setForm(nextForm);
  }, []);

  const acceptSavedForm = useCallback((nextForm: CollectionEditorState) => {
    formRef.current = nextForm;
    baselineRef.current = nextForm;
    setForm(nextForm);
    setBaseline(nextForm);
  }, []);

  useEffect(() => {
    if (!collectionKey || !savedForm) {
      collectionKeyRef.current = null;
      return;
    }

    if (
      shouldRefreshCollectionEditorDraft(
        formRef.current,
        baselineRef.current,
        collectionKeyRef.current,
        collectionKey,
      )
    ) {
      acceptSavedForm(savedForm);
      setError("");
      setRemovedMedia({ poster: false, backdrop: false });
    }
    collectionKeyRef.current = collectionKey;
  }, [acceptSavedForm, collectionKey, savedForm]);

  useEffect(() => {
    if (!sourceSelection) return;
    replaceForm({
      ...formRef.current,
      source_type: sourceSelection.sourceType,
      source_value: sourceSelection.sourceValue,
      source_origin: sourceSelection.sourceOrigin,
    });
  }, [replaceForm, sourceSelection]);

  const dirty =
    collection !== undefined && !collectionEditorStateMatches(form, baseline);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(
    () => () => onDirtyChange?.(false),
    [onDirtyChange],
  );

  if (collection === undefined) return null;

  function update(changes: Partial<CollectionEditorState>) {
    replaceForm({ ...formRef.current, ...changes });
  }

  function resetForm() {
    if (!savedForm) return;
    acceptSavedForm(savedForm);
    setError("");
  }

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Modifiche non salvate",
      description:
        "Chiudere l'editor e perdere le modifiche a questa collezione?",
      confirmLabel: "Abbandona modifiche",
      tone: "danger",
    });
    if (confirmed) onClose();
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !form.name.trim() ||
      !form.source_type ||
      !form.source_value.trim() ||
      !form.server_ids.length
    ) {
      return setError(
        "Nome, fonte, valore della fonte e almeno un server sono obbligatori.",
      );
    }
    setError("");
    try {
      const { poster, backdrop, ...input } = form;
      await onSave(
        {
          ...input,
          id: collection?.id,
          name: input.name.trim(),
          sort_name: input.sort_name.trim() || input.name.trim(),
          source_value: input.source_value.trim(),
          collection_sort_name:
            input.collection_sort_name?.trim() ||
            input.sort_name.trim() ||
            input.name.trim(),
        },
        { poster, backdrop },
      );
      onClose();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Salvataggio collezione non riuscito.",
      );
    }
  }

  async function removeImage(kind: "poster" | "backdrop") {
    if (!collection?.id) return;
    setRemoving(kind);
    try {
      await onRemoveImage(collection.id, kind);
      setRemovedMedia((current) => ({ ...current, [kind]: true }));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Rimozione immagine non riuscita.",
      );
    } finally {
      setRemoving(null);
    }
  }

  return (
    <>
      <DialogBackdrop
        className="users-dialog-backdrop"
        dismissible={!saving}
        onDismiss={() => void requestClose()}
      >
        <section
          className="collection-editor-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="collection-editor-title"
        >
          <form className="collection-editor-form" onSubmit={submit}>
            <header>
              <div>
                <h2 id="collection-editor-title" className="contextual-heading" title="Definizione collezione">
                  {collection
                    ? `Modifica ${collection.name}`
                    : "Crea collezione"}
                </h2>
                <p>
                  Configura fonte, server, automazioni e immagini senza uscire
                  dalla nuova interfaccia.
                </p>
              </div>
              <Button
                type="button"
                variant="secondary"
                className="collection-editor-mobile-sources"
                onClick={onOpenSources}
                disabled={saving}
              >
                <ListPlus size={16} aria-hidden="true" />
                Fonti
              </Button>
            </header>
          {error ? (
            <p className="users-dialog-error" role="alert">
              {error}
            </p>
          ) : null}
          <CollectionEditorCoreFields
            form={form}
            options={options}
            disabled={saving}
            onUpdate={update}
          />
          <CollectionEditorMediaFields
            collection={collection}
            form={form}
            disabled={saving}
            removing={removing}
            removed={removedMedia}
            onUpdate={update}
            onRemove={(kind) => void removeImage(kind)}
          />
          <CollectionEditorAutomationFields
            form={form}
            disabled={saving}
            onUpdate={update}
          />
          <footer>
            <Button
              type="button"
              variant="ghost"
              onClick={() => void requestClose()}
              disabled={saving}
            >
              Annulla
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="compact"
              onClick={resetForm}
              disabled={saving}
            >
              <RotateCcw size={15} aria-hidden="true" /> Ripristina
            </Button>
            <Button type="submit" variant="primary" disabled={saving || !options}>
              {saving ? "Salvataggio..." : "Salva collezione"}
            </Button>
          </footer>
          </form>
          <aside className="collection-editor-sources" aria-label="Fonti collezione">
            <header>
              <h3>Fonti</h3>
              <p>Usa liste salvate o personali per compilare la fonte della collezione.</p>
            </header>
            <CollectionSourcesPanel
              enabled={collection !== undefined}
              options={options}
              onSelect={onSelectSource}
              onDirtyChange={onSourcesDirtyChange}
            />
          </aside>
        </section>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

export { CollectionEditorDialog };
