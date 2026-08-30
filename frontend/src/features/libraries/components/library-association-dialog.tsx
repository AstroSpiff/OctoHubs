import { EyeOff, RotateCcw, Save, X } from "@/components/ui/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { libraryAssociationDraftMatches } from "@/features/libraries/library-dialog-draft";
import {
  hiddenLibraryGroupName,
  libraryTypeBucket,
  libraryTypeLabel,
} from "@/features/libraries/presentation";
import type {
  LibraryAssociation,
  LibraryEntry,
  LibraryGroup,
} from "@/features/libraries/types";

type ManagedLibrary = LibraryEntry & {
  key: string;
  collectionType: string;
  automaticGroup: string;
};

type LibraryAssociationDialogProps = {
  open: boolean;
  ready: boolean;
  groups: LibraryGroup[];
  associations: LibraryAssociation[];
  saving: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  onClose: () => void;
  onSave: (associations: LibraryAssociation[]) => Promise<void>;
};

function libraryKey(
  library: Pick<LibraryEntry, "server_id" | "library_id" | "id">,
) {
  return `${library.server_id}:${library.library_id || library.id || ""}`;
}

function managedLibraries(groups: LibraryGroup[]): ManagedLibrary[] {
  const seen = new Set<string>();
  return groups
    .flatMap((group) =>
      group.libraries.map((library) => ({
        ...library,
        key: libraryKey(library),
        collectionType: group.collection_type,
        automaticGroup: group.group_name,
      })),
    )
    .filter((library) => {
      if ((!library.library_id && !library.id) || seen.has(library.key))
        return false;
      seen.add(library.key);
      return true;
    });
}

function LibraryAssociationDialog({
  open,
  ready,
  groups,
  associations,
  saving,
  onDirtyChange,
  onClose,
  onSave,
}: LibraryAssociationDialogProps) {
  const confirmation = useConfirmationDialog();
  const libraries = useMemo(() => managedLibraries(groups), [groups]);
  const savedAssociations = useMemo(
    () =>
      new Map(
        associations.map((association) => [
          `${association.server_id}:${association.library_id}`,
          association.group_name,
        ]),
      ),
    [associations],
  );
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [baseline, setBaseline] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const initializedForOpen = useRef(false);
  const draftRef = useRef(draft);
  const baselineRef = useRef(baseline);
  const incomingDraft = useMemo(
    () =>
      Object.fromEntries(
        libraries.map((library) => [
          library.key,
          savedAssociations.get(library.key) || "",
        ]),
      ),
    [libraries, savedAssociations],
  );

  const acceptIncomingDraft = useCallback((nextDraft: Record<string, string>) => {
    draftRef.current = nextDraft;
    baselineRef.current = nextDraft;
    setDraft(nextDraft);
    setBaseline(nextDraft);
  }, []);

  useEffect(() => {
    if (!open) {
      initializedForOpen.current = false;
      return;
    }
    if (!ready || initializedForOpen.current) return;
    setSearch("");
    setError("");
    acceptIncomingDraft(incomingDraft);
    initializedForOpen.current = true;
  }, [acceptIncomingDraft, incomingDraft, open, ready]);

  useEffect(() => {
    if (!open || !ready || !initializedForOpen.current) return;
    if (!libraryAssociationDraftMatches(draftRef.current, baselineRef.current))
      return;
    if (libraryAssociationDraftMatches(baselineRef.current, incomingDraft))
      return;
    acceptIncomingDraft(incomingDraft);
  }, [acceptIncomingDraft, incomingDraft, open, ready]);

  const lowerSearch = search.trim().toLocaleLowerCase("it-IT");
  const visible = libraries.filter(
    (library) =>
      !lowerSearch ||
      [
        library.library_name,
        library.server_alias,
        library.server_name,
        library.automaticGroup,
      ].some((value) =>
        value?.toLocaleLowerCase("it-IT").includes(lowerSearch),
      ),
  );

  const groupNamesByType = useMemo(() => {
    const values = new Map<string, string[]>();
    for (const group of groups) {
      const existing = values.get(group.collection_type) || [];
      if (group.group_name && !existing.includes(group.group_name))
        existing.push(group.group_name);
      values.set(
        group.collection_type,
        existing.sort((first, second) => first.localeCompare(second, "it")),
      );
    }
    return values;
  }, [groups]);

  const dirty = !libraryAssociationDraftMatches(draft, baseline);

  useEffect(() => {
    onDirtyChange?.(open && dirty);
  }, [dirty, onDirtyChange, open]);

  useEffect(
    () => () => onDirtyChange?.(false),
    [onDirtyChange],
  );

  if (!open) return null;

  function update(library: ManagedLibrary, value: string) {
    const nextDraft = { ...draftRef.current, [library.key]: value };
    draftRef.current = nextDraft;
    setDraft(nextDraft);
  }

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Associazioni non salvate",
      description:
        "Chiudere e perdere le modifiche alle associazioni delle librerie?",
      confirmLabel: "Abbandona modifiche",
      tone: "danger",
    });
    if (confirmed) onClose();
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const payload = libraries.flatMap((library) => {
      const groupName = draft[library.key]?.trim();
      const libraryId = library.library_id || library.id;
      return groupName && libraryId
        ? [
            {
              server_id: library.server_id,
              library_id: libraryId,
              group_name: groupName,
            },
          ]
        : [];
    });
    try {
      await onSave(payload);
      onClose();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Impossibile salvare le associazioni.",
      );
    }
  }

  return (
    <>
      <DialogBackdrop
        className="users-dialog-backdrop"
        dismissible={!saving}
        onDismiss={() => void requestClose()}
      >
      <form
        className="library-associations-dialog"
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="library-associations-title"
      >
        <header>
          <div>
            <h2 id="library-associations-title" className="contextual-heading" title="Associazioni librerie">Raggruppamento manuale</h2>
            <p>
              Lascia vuoto un campo per usare il raggruppamento automatico;
              scegli o scrivi un nome per forzare un gruppo.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Chiudi"
            aria-label="Chiudi"
            onClick={() => void requestClose()}
            disabled={saving}
          >
            <X size={18} aria-hidden="true" />
          </Button>
        </header>
        {error ? (
          <p className="users-dialog-error" role="alert">
            {error}
          </p>
        ) : null}
        <label className="library-associations-search">
          <span>Filtra librerie</span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Nome libreria o server..."
            disabled={saving}
          />
        </label>
        <div className="library-association-columns">
          {(["movies", "tvshows", "other"] as const).map((bucket) => {
            const items = visible.filter(
              (library) => libraryTypeBucket(library.collectionType) === bucket,
            );
            return (
              <section key={bucket} className="library-association-column">
                <h3>{libraryTypeLabel(bucket)}</h3>
                <datalist id={`library-group-options-${bucket}`}>
                  <option value={hiddenLibraryGroupName} />
                  {[
                    ...new Set(
                      groups
                        .filter(
                          (group) =>
                            libraryTypeBucket(group.collection_type) === bucket,
                        )
                        .flatMap(
                          (group) =>
                            groupNamesByType.get(group.collection_type) || [],
                        ),
                    ),
                  ]
                    .filter((name) => name !== hiddenLibraryGroupName)
                    .map((name) => (
                      <option key={name} value={name} />
                    ))}
                </datalist>
                {!items.length ? (
                  <p>Nessuna libreria.</p>
                ) : (
                  items.map((library) => (
                    <LibraryAssociationRow
                      key={library.key}
                      library={library}
                      value={draft[library.key] || ""}
                      listId={`library-group-options-${bucket}`}
                      disabled={saving}
                      onChange={update}
                    />
                  ))
                )}
              </section>
            );
          })}
        </div>
        <footer>
          <Button
            type="button"
            variant="ghost"
            onClick={() => void requestClose()}
            disabled={saving}
          >
            Annulla
          </Button>
          <Button type="submit" variant="primary" disabled={saving}>
            <Save size={16} aria-hidden="true" />
            {saving ? "Salvataggio..." : "Salva associazioni"}
          </Button>
        </footer>
        </form>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

function LibraryAssociationRow({
  library,
  value,
  listId,
  disabled,
  onChange,
}: {
  library: ManagedLibrary;
  value: string;
  listId: string;
  disabled: boolean;
  onChange: (library: ManagedLibrary, value: string) => void;
}) {
  const serverName =
    library.server_alias || library.server_name || library.server_id;
  return (
    <article className="library-association-row">
      <div>
        <strong>{library.library_name || "Libreria"}</strong>
        <small>{serverName}</small>
        <span>
          {value === hiddenLibraryGroupName
            ? "Nascosta dalla griglia"
            : `Automatico: ${library.automaticGroup || "nessun gruppo"}`}
        </span>
      </div>
      <div className="library-association-input">
        <input
          list={listId}
          value={value}
          onChange={(event) => onChange(library, event.target.value)}
          placeholder={library.automaticGroup || "Nome gruppo"}
          disabled={disabled}
          aria-label={`Gruppo manuale per ${library.library_name || "libreria"}`}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Nascondi dalla griglia librerie"
          aria-label={`Nascondi ${library.library_name || "libreria"}`}
          onClick={() => onChange(library, hiddenLibraryGroupName)}
          disabled={disabled || value === hiddenLibraryGroupName}
        >
          <EyeOff size={15} aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Ripristina raggruppamento automatico"
          aria-label={`Ripristina raggruppamento automatico per ${library.library_name || "libreria"}`}
          onClick={() => onChange(library, "")}
          disabled={disabled || !value}
        >
          <RotateCcw size={15} aria-hidden="true" />
        </Button>
      </div>
    </article>
  );
}

export { LibraryAssociationDialog };
