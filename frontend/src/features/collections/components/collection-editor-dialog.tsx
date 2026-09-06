import { ListPlus, RotateCcw, X } from "@/components/ui/icons";
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
  promoteNewCollectionEditorDraft,
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
  onCloseSources: () => void;
  sourcesOpen: boolean;
  onSelectSource: (selection: SourceSelection) => void;
  sourceSelection?: SourceSelection | null;
  sourcesDirty?: boolean;
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
  onCloseSources,
  sourcesOpen,
  onSelectSource,
  sourceSelection,
  sourcesDirty = false,
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
  const [sourcesHidden, setSourcesHidden] = useState(false);
  const [sourcesBusy, setSourcesBusy] = useState(false);
  const formRef = useRef(form);
  const baselineRef = useRef(baseline);
  const formRevisionRef = useRef(0);
  const sourcesBusyRef = useRef(false);
  const sourcesDirtyRef = useRef(sourcesDirty);
  const collectionKeyRef = useRef<string | null>(null);
  const sourcesButtonRef = useRef<HTMLButtonElement>(null);
  const sourcesCloseButtonRef = useRef<HTMLButtonElement>(null);
  const sourcesWasOpenRef = useRef(false);
  const collectionKey =
    collection === undefined ? null : collection?.id || "__new_collection__";
  const savedForm = useMemo(
    () =>
      collection === undefined
        ? null
        : collectionEditorState(collection, options),
    [collection, options],
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return undefined;
    }
    const media = window.matchMedia("(max-width: 680px)");
    const update = () => setSourcesHidden(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!sourcesHidden) {
      sourcesWasOpenRef.current = sourcesOpen;
      return;
    }
    if (sourcesOpen) {
      sourcesCloseButtonRef.current?.focus();
    } else if (sourcesWasOpenRef.current) {
      sourcesButtonRef.current?.focus();
    }
    sourcesWasOpenRef.current = sourcesOpen;
  }, [sourcesHidden, sourcesOpen]);

  const replaceForm = useCallback((nextForm: CollectionEditorState) => {
    formRevisionRef.current += 1;
    formRef.current = nextForm;
    setForm(nextForm);
  }, []);

  sourcesDirtyRef.current = sourcesDirty;

  const acceptSavedForm = useCallback((nextForm: CollectionEditorState) => {
    formRef.current = nextForm;
    baselineRef.current = nextForm;
    setForm(nextForm);
    setBaseline(nextForm);
  }, []);

  const handleSourcesBusyChange = useCallback((nextBusy: boolean) => {
    sourcesBusyRef.current = nextBusy;
    setSourcesBusy(nextBusy);
  }, []);

  useEffect(() => {
    if (!collectionKey || !savedForm) {
      collectionKeyRef.current = null;
      return;
    }

    const previousCollectionKey = collectionKeyRef.current;
    if (
      shouldRefreshCollectionEditorDraft(
        formRef.current,
        baselineRef.current,
        previousCollectionKey,
        collectionKey,
      )
    ) {
      if (
        previousCollectionKey === "__new_collection__" &&
        collectionKey !== "__new_collection__"
      ) {
        const promotedDraft = promoteNewCollectionEditorDraft(
          formRef.current,
          savedForm,
        );
        formRef.current = promotedDraft;
        baselineRef.current = savedForm;
        setForm(promotedDraft);
        setBaseline(savedForm);
      } else {
        acceptSavedForm(savedForm);
      }
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
    if (saving || sourcesBusy) return;
    if (!dirty && !sourcesDirty) {
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
    if (saving || sourcesBusy) return;
    if (sourcesDirtyRef.current) {
      setError(
        "Salva o svuota prima la bozza della fonte: non fa parte del salvataggio della collezione.",
      );
      return;
    }
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
    const submittedRevision = formRevisionRef.current;
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
      if (
        formRevisionRef.current === submittedRevision &&
        !sourcesDirtyRef.current &&
        !sourcesBusyRef.current
      ) {
        onClose();
      } else {
        setError(
          "Collezione salvata. Le modifiche iniziate durante il salvataggio restano aperte e non sono state scartate.",
        );
      }
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
        dismissible={!saving && !sourcesBusy}
        onDismiss={() => void requestClose()}
      >
        <section
          className="collection-editor-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="collection-editor-title"
        >
          <form
            className="collection-editor-form"
            onSubmit={submit}
            aria-hidden={(sourcesHidden && sourcesOpen) || undefined}
            inert={sourcesHidden && sourcesOpen ? true : undefined}
          >
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
                ref={sourcesButtonRef}
                type="button"
                variant="secondary"
                className="collection-editor-mobile-sources"
                onClick={onOpenSources}
                disabled={saving || sourcesBusy}
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
              disabled={saving || sourcesBusy}
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
            <Button type="submit" variant="primary" disabled={saving || sourcesBusy || !options}>
              {saving ? "Salvataggio..." : "Salva collezione"}
            </Button>
          </footer>
          </form>
          <aside
            className={`collection-editor-sources${sourcesHidden && sourcesOpen ? " collection-editor-sources--mobile-open" : ""}`}
            aria-label="Fonti collezione"
            aria-hidden={(sourcesHidden && !sourcesOpen) || undefined}
            inert={sourcesHidden && !sourcesOpen ? true : undefined}
            onKeyDown={(event) => {
              if (sourcesHidden && sourcesOpen && !sourcesBusy && event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                onCloseSources();
              }
            }}
          >
            <header>
              <div>
                <h3>Fonti</h3>
                <p>Usa liste salvate o personali per compilare la fonte della collezione.</p>
              </div>
              <Button
                ref={sourcesCloseButtonRef}
                type="button"
                variant="ghost"
                size="icon"
                className="collection-editor-sources-close"
                title="Chiudi fonti"
                aria-label="Chiudi fonti"
                onClick={onCloseSources}
                disabled={sourcesBusy}
              >
                <X size={17} aria-hidden="true" />
              </Button>
            </header>
            <CollectionSourcesPanel
              enabled={collection !== undefined}
              disabled={saving}
              options={options}
              onSelect={onSelectSource}
              onDirtyChange={onSourcesDirtyChange}
              onBusyChange={handleSourcesBusyChange}
            />
          </aside>
        </section>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

export { CollectionEditorDialog };
