import { Save, X } from "@/components/ui/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { LibraryOrderRow } from "@/features/libraries/components/library-order-row";
import {
  libraryGroupOrderMatches,
  libraryServerOrderMatches,
} from "@/features/libraries/library-dialog-draft";
import {
  libraryGroupOrder,
  libraryTypeLabel,
  moveLibraryOrderItem,
  moveLibraryOrderItemTo,
} from "@/features/libraries/presentation";
import type {
  LibraryActionTarget,
  LibraryGroup,
} from "@/features/libraries/types";

type LibraryOrderDialogProps = {
  open: boolean;
  ready: boolean;
  groups: LibraryGroup[];
  servers: LibraryActionTarget[];
  savingGroups: boolean;
  savingServers: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  onClose: () => void;
  onSaveGroupOrder: (
    order: ReturnType<typeof libraryGroupOrder>,
  ) => Promise<void>;
  onSaveServerOrder: (serverIds: string[]) => Promise<void>;
};

function LibraryOrderDialog({
  open,
  ready,
  groups,
  servers,
  savingGroups,
  savingServers,
  onDirtyChange,
  onClose,
  onSaveGroupOrder,
  onSaveServerOrder,
}: LibraryOrderDialogProps) {
  const confirmation = useConfirmationDialog();
  const [groupDraft, setGroupDraft] = useState<LibraryGroup[]>(() =>
    open && ready ? groups : [],
  );
  const [serverDraft, setServerDraft] = useState<LibraryActionTarget[]>(() =>
    open && ready ? servers : [],
  );
  const [groupBaseline, setGroupBaseline] = useState<LibraryGroup[]>(() =>
    open && ready ? groups : [],
  );
  const [serverBaseline, setServerBaseline] = useState<LibraryActionTarget[]>(() =>
    open && ready ? servers : [],
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dragging, setDragging] = useState<
    | { kind: "group"; collectionType: string; id: string }
    | { kind: "server"; id: string }
    | null
  >(null);
  const initializedForOpen = useRef(open && ready);
  const groupDraftRef = useRef(groupDraft);
  const serverDraftRef = useRef(serverDraft);
  const groupBaselineRef = useRef(groupBaseline);
  const serverBaselineRef = useRef(serverBaseline);

  const replaceGroupDraft = useCallback((nextDraft: LibraryGroup[]) => {
    groupDraftRef.current = nextDraft;
    setGroupDraft(nextDraft);
  }, []);
  const replaceServerDraft = useCallback((nextDraft: LibraryActionTarget[]) => {
    serverDraftRef.current = nextDraft;
    setServerDraft(nextDraft);
  }, []);
  const acceptGroupDraft = useCallback((nextDraft: LibraryGroup[]) => {
    groupDraftRef.current = nextDraft;
    groupBaselineRef.current = nextDraft;
    setGroupDraft(nextDraft);
    setGroupBaseline(nextDraft);
  }, []);
  const acceptServerDraft = useCallback((nextDraft: LibraryActionTarget[]) => {
    serverDraftRef.current = nextDraft;
    serverBaselineRef.current = nextDraft;
    setServerDraft(nextDraft);
    setServerBaseline(nextDraft);
  }, []);

  useEffect(() => {
    if (!open) {
      initializedForOpen.current = false;
      return;
    }
    if (!ready) return;
    const opening = !initializedForOpen.current;
    const localChanges =
      !libraryGroupOrderMatches(groupDraftRef.current, groupBaselineRef.current) ||
      !libraryServerOrderMatches(serverDraftRef.current, serverBaselineRef.current);
    if (!opening && localChanges) return;
    acceptGroupDraft(groups);
    acceptServerDraft(servers);
    if (opening) {
      setError("");
      setNotice("");
      setDragging(null);
    }
    initializedForOpen.current = true;
  }, [
    acceptGroupDraft,
    acceptServerDraft,
    groups,
    open,
    ready,
    servers,
  ]);

  const groupsByType = useMemo(() => {
    const result = new Map<string, LibraryGroup[]>();
    for (const group of groupDraft) {
      const entries = result.get(group.collection_type) || [];
      entries.push(group);
      result.set(group.collection_type, entries);
    }
    return [...result.entries()];
  }, [groupDraft]);

  const dirty =
    !libraryGroupOrderMatches(groupDraft, groupBaseline) ||
    !libraryServerOrderMatches(serverDraft, serverBaseline);

  useEffect(() => {
    onDirtyChange?.(open && dirty);
  }, [dirty, onDirtyChange, open]);

  useEffect(
    () => () => onDirtyChange?.(false),
    [onDirtyChange],
  );

  if (!open) return null;

  function moveGroup(collectionType: string, index: number, direction: -1 | 1) {
    const section = groupDraftRef.current.filter(
      (group) => group.collection_type === collectionType,
    );
    const moved = moveLibraryOrderItem(section, index, direction);
    if (moved === section) return;
    setNotice("");
    const byType = new Map<string, LibraryGroup[]>();
    for (const [type, current] of groupsByType) byType.set(type, current);
    byType.set(collectionType, moved);
    replaceGroupDraft(
      groupsByType.flatMap(([type]) => byType.get(type) || []),
    );
  }

  function moveServer(index: number, direction: -1 | 1) {
    setNotice("");
    replaceServerDraft(
      moveLibraryOrderItem(serverDraftRef.current, index, direction),
    );
  }

  function moveGroupTo(
    collectionType: string,
    groupName: string,
    targetGroupName: string,
    after: boolean,
  ) {
    const entries = groupDraftRef.current.filter(
      (group) => group.collection_type === collectionType,
    );
    const fromIndex = entries.findIndex((group) => group.group_name === groupName);
    const targetIndex = entries.findIndex(
      (group) => group.group_name === targetGroupName,
    );
    const moved = moveLibraryOrderItemTo(entries, fromIndex, targetIndex, after);
    if (moved === entries) return;
    setNotice("");
    let index = 0;
    replaceGroupDraft(
      groupDraftRef.current.map((group) =>
        group.collection_type === collectionType ? moved[index++] : group,
      ),
    );
  }

  function moveServerTo(serverId: string, targetServerId: string, after: boolean) {
    const fromIndex = serverDraftRef.current.findIndex(
      (server) => server.id === serverId,
    );
    const targetIndex = serverDraftRef.current.findIndex(
      (server) => server.id === targetServerId,
    );
    const moved = moveLibraryOrderItemTo(
      serverDraftRef.current,
      fromIndex,
      targetIndex,
      after,
    );
    if (moved === serverDraftRef.current) return;
    setNotice("");
    replaceServerDraft(moved);
  }

  async function saveGroupOrder() {
    setError("");
    setNotice("");
    try {
      const savedDraft = groupDraftRef.current;
      await onSaveGroupOrder(libraryGroupOrder(savedDraft));
      groupBaselineRef.current = savedDraft;
      setGroupBaseline(savedDraft);
      setNotice("Ordine dei gruppi salvato.");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Impossibile salvare l'ordine.",
      );
    }
  }

  async function saveServerOrder() {
    setError("");
    setNotice("");
    try {
      const savedDraft = serverDraftRef.current;
      await onSaveServerOrder(savedDraft.map((server) => server.id));
      serverBaselineRef.current = savedDraft;
      setServerBaseline(savedDraft);
      setNotice("Ordine dei server salvato.");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Impossibile salvare l'ordine.",
      );
    }
  }

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Ordine non salvato",
      description:
        "Chiudere e perdere le modifiche all'ordine di gruppi e server?",
      confirmLabel: "Abbandona modifiche",
      tone: "danger",
    });
    if (confirmed) onClose();
  }

  const saving = savingGroups || savingServers;
  const busy = saving || !ready;

  return (
    <>
      <DialogBackdrop
        className="users-dialog-backdrop"
        dismissible={!saving}
        onDismiss={() => void requestClose()}
      >
        <section
          className="library-order-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="library-order-title"
          aria-busy={busy}
        >
          <header>
            <div>
              <h2 id="library-order-title" className="contextual-heading" title="Organizzazione">Ordine librerie e server</h2>
              <p>
                Questo ordine viene mantenuto nelle schermate Emby e nelle
                operazioni successive.
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
          {notice ? (
            <p className="library-order-notice" role="status">
              {notice}
            </p>
          ) : null}
          {saving ? (
            <p className="library-order-saving" role="status">
              Salvataggio ordine in corso...
            </p>
          ) : null}
          {!ready ? (
            <div className="loading-state">
              Caricamento ordine librerie e server...
            </div>
          ) : null}
          {ready ? (
            <div className="library-order-sections">
              <section aria-labelledby="library-group-order-title">
                <div className="library-order-section-heading">
                  <div>
                    <h3 id="library-group-order-title">Gruppi librerie</h3>
                    <p>Il movimento resta all'interno dello stesso tipo.</p>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    size="compact"
                    onClick={() => void saveGroupOrder()}
                    disabled={busy}
                  >
                    <Save size={15} aria-hidden="true" />
                    {savingGroups ? "Salvataggio..." : "Salva gruppi"}
                  </Button>
                </div>
                {groupsByType.map(([collectionType, entries]) => (
                  <fieldset key={collectionType} className="library-order-list">
                    <legend>{libraryTypeLabel(collectionType)}</legend>
                    {entries.map((group, index) => (
                      <LibraryOrderRow
                        key={`${collectionType}:${group.group_name}`}
                        label={group.group_name || "Gruppo senza nome"}
                        secondary={`${group.libraries.length} ${group.libraries.length === 1 ? "libreria" : "librerie"}`}
                        index={index}
                        total={entries.length}
                        disabled={busy}
                        onMove={(direction) =>
                          moveGroup(collectionType, index, direction)
                        }
                        dragging={
                          dragging?.kind === "group" &&
                          dragging.collectionType === collectionType &&
                          dragging.id === group.group_name
                        }
                        onDragStart={() =>
                          setDragging({
                            kind: "group",
                            collectionType,
                            id: group.group_name,
                          })
                        }
                        onDrop={(after) => {
                          if (
                            dragging?.kind !== "group" ||
                            dragging.collectionType !== collectionType ||
                            dragging.id === group.group_name
                          ) {
                            return;
                          }
                          moveGroupTo(
                            collectionType,
                            dragging.id,
                            group.group_name,
                            after,
                          );
                        }}
                        onDragEnd={() => setDragging(null)}
                      />
                    ))}
                  </fieldset>
                ))}
                {!groupsByType.length ? (
                  <p className="library-order-empty">
                    Nessun gruppo disponibile.
                  </p>
                ) : null}
              </section>
              <section aria-labelledby="library-server-order-title">
                <div className="library-order-section-heading">
                  <div>
                    <h3 id="library-server-order-title">Server Emby</h3>
                    <p>Influenza la sequenza dei server nelle operazioni.</p>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    size="compact"
                    onClick={() => void saveServerOrder()}
                    disabled={busy}
                  >
                    <Save size={15} aria-hidden="true" />
                    {savingServers ? "Salvataggio..." : "Salva server"}
                  </Button>
                </div>
                <div className="library-order-list" role="list">
                  {serverDraft.map((server, index) => (
                    <LibraryOrderRow
                      key={server.id}
                      label={server.name}
                      index={index}
                      total={serverDraft.length}
                      disabled={busy}
                      onMove={(direction) => moveServer(index, direction)}
                      dragging={
                        dragging?.kind === "server" && dragging.id === server.id
                      }
                      onDragStart={() =>
                        setDragging({ kind: "server", id: server.id })
                      }
                      onDrop={(after) => {
                        if (
                          dragging?.kind !== "server" ||
                          dragging.id === server.id
                        ) {
                          return;
                        }
                        moveServerTo(dragging.id, server.id, after);
                      }}
                      onDragEnd={() => setDragging(null)}
                    />
                  ))}
                  {!serverDraft.length ? (
                    <p className="library-order-empty">
                      Nessun server abilitato.
                    </p>
                  ) : null}
                </div>
              </section>
            </div>
          ) : null}
          <footer>
            <Button
              type="button"
              variant="primary"
              onClick={() => void requestClose()}
              disabled={saving}
            >
              Chiudi
            </Button>
          </footer>
        </section>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

export { LibraryOrderDialog };
