import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { useDirtyChange } from "@/lib/use-dirty-change";
import { checkUserName } from "@/features/users/api";
import { ServerIdentity } from "@/features/users/components/server-identity";
import { duplicateCloneGroupNames } from "@/features/users/clone-group-warning";
import {
  cloneUserDraft,
  cloneUserDraftMatches,
} from "@/features/users/clone-user-draft";
import { userConfigurationCategories } from "@/features/users/user-configuration-categories";
import type {
  BulkCloneInput,
  EmbyUser,
  EmbyUserGroup,
  EmbyUserServer,
} from "@/features/users/types";

type CloneUserDialogProps = {
  users: EmbyUser[];
  groups: EmbyUserGroup[];
  servers: EmbyUserServer[];
  cloning: boolean;
  mutationError?: string;
  onClose: () => void;
  onClone: (input: BulkCloneInput) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function CloneUserDialog({
  users,
  groups,
  servers,
  cloning,
  mutationError,
  onClose,
  onClone,
  onDirtyChange,
}: CloneUserDialogProps) {
  const confirmation = useConfirmationDialog();
  const [draft, setDraft] = useState<BulkCloneInput>(() => cloneUserDraft(users, servers));
  const [baseline, setBaseline] = useState<BulkCloneInput>(() => cloneUserDraft(users, servers));
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState("");
  const previousSourcesKey = useRef<string | null>(null);
  const sourcesKey = users.map((user) => `${user.server_id}:${user.user_id}`).join("|");

  const operationCount = draft.sources.reduce(
    (count, source) =>
      count +
      draft.targetServerIds.filter(
        (serverId) => serverId !== source.user.server_id,
      ).length,
    0,
  );
  const dirty = !cloneUserDraftMatches(draft, baseline);
  const duplicateGroupNames = duplicateCloneGroupNames(users, groups);
  const allSourcesLinked = draft.sources.length > 0 && draft.sources.every(
    (source) => source.linkGroup,
  );
  useDirtyChange(users.length > 0, dirty, onDirtyChange);

  useEffect(() => {
    if (previousSourcesKey.current === sourcesKey) return;

    previousSourcesKey.current = sourcesKey;
    const nextDraft = cloneUserDraft(users, servers);
    setDraft(nextDraft);
    setBaseline(nextDraft);
    setError("");
  }, [sourcesKey, users, servers]);

  if (!users.length) return null;

  function toggleTarget(serverId: string) {
    setDraft((current) => ({
      ...current,
      targetServerIds: current.targetServerIds.includes(serverId)
        ? current.targetServerIds.filter((id) => id !== serverId)
        : [...current.targetServerIds, serverId],
    }));
  }

  function updateSource(
    index: number,
    updates: Partial<BulkCloneInput["sources"][number]>,
  ) {
    setDraft((current) => ({
      ...current,
      sources: current.sources.map((source, itemIndex) =>
        itemIndex === index ? { ...source, ...updates } : source,
      ),
    }));
  }

  function toggleConfigCategory(categoryId: string) {
    setDraft((current) => ({
      ...current,
      configCategories: current.configCategories.includes(categoryId)
        ? current.configCategories.filter((id) => id !== categoryId)
        : [...current.configCategories, categoryId],
    }));
  }

  function setAllSourceLinks(linkGroup: boolean) {
    setDraft((current) => ({
      ...current,
      sources: current.sources.map((source) => ({ ...source, linkGroup })),
    }));
  }

  async function requestClose() {
    if (cloning || validating) return;
    if (!dirty) {
      onClose();
      return;
    }

    const confirmed = await confirmation.confirm({
      title: "Clonazione non completata",
      description: "Chiudere e perdere la configurazione delle copie?",
      confirmLabel: "Abbandona clonazione",
      tone: "danger",
    });
    if (confirmed) onClose();
  }

  async function verifyAndClone(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedSources = draft.sources.map((source) => ({
      ...source,
      newUsername: source.newUsername.trim(),
    }));
    const targets = draft.targetServerIds.filter((serverId) =>
      trimmedSources.some((source) => source.user.server_id !== serverId),
    );
    if (!targets.length) return setError("Seleziona almeno un server diverso da quello sorgente.");
    if (trimmedSources.some((source) => !source.newUsername)) return setError("Ogni copia deve avere un nome utente.");

    const duplicateNames = new Map<string, string>();
    for (const source of trimmedSources) {
      for (const targetServerId of targets) {
        if (targetServerId === source.user.server_id) continue;
        const key = `${targetServerId}:${source.newUsername.toLocaleLowerCase("it")}`;
        if (duplicateNames.has(key)) return setError(`Più copie usano il nome ${source.newUsername} sullo stesso server di destinazione.`);
        duplicateNames.set(key, source.newUsername);
      }
    }

    setError("");
    setValidating(true);
    try {
      const conflicts: string[] = [];
      for (const source of trimmedSources) {
        for (const targetServerId of targets) {
          if (targetServerId === source.user.server_id) continue;
          const result = await checkUserName(targetServerId, source.newUsername);
          if (result.exists) {
            const server = servers.find((item) => item.id === targetServerId);
            conflicts.push(`${source.newUsername} su ${server?.name || targetServerId}`);
          }
        }
      }
      if (conflicts.length) {
        setError(`Esistono già utenti con questi nomi: ${conflicts.join(", ")}.`);
        return;
      }
      onClone({
        ...draft,
        sources: trimmedSources,
        targetServerIds: targets,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossibile verificare i nomi utente.");
    } finally {
      setValidating(false);
    }
  }

  return (
    <>
      <DialogBackdrop
        className="users-dialog-backdrop"
        dismissible={!cloning && !validating}
        onDismiss={() => void requestClose()}
      >
        <form className="users-clone-dialog users-clone-dialog--bulk" onSubmit={verifyAndClone} role="dialog" aria-modal="true" aria-labelledby="clone-dialog-title">
        <header>
          <h2 id="clone-dialog-title" className="contextual-heading" title="Clonazione utenti">{users.length === 1 ? `Clona ${users[0].name}` : `Clona ${users.length} utenti`}</h2>
          <p>Ogni copia viene verificata prima della creazione. Le copie verso il proprio server sorgente non vengono eseguite.</p>
        </header>
        {duplicateGroupNames.length ? (
          <p className="users-clone-warning" role="status">
            <strong>Attenzione.</strong> Hai selezionato più utenti del gruppo{" "}
            <strong>{duplicateGroupNames.join(", ")}</strong>: sui server di
            destinazione verranno create copie distinte per ogni utente.
          </p>
        ) : null}
        {error || mutationError ? <p className="users-dialog-error" role="alert">{error || mutationError}</p> : null}
        <fieldset>
          <legend>Server di destinazione</legend>
          <div className="users-clone-server-list">
            {servers.map((server) => {
              const onlyOwnSource = users.every((user) => user.server_id === server.id);
              return <label key={server.id} className={onlyOwnSource ? "is-unavailable" : ""}><input type="checkbox" checked={draft.targetServerIds.includes(server.id)} disabled={onlyOwnSource || cloning || validating} onChange={() => toggleTarget(server.id)} /><ServerIdentity name={server.name} icon={server.icon} color={onlyOwnSource ? undefined : server.icon_color} iconStyle={server.icon_style} />{onlyOwnSource ? <small>server sorgente</small> : null}</label>;
            })}
          </div>
        </fieldset>
        <fieldset>
          <legend>Nomi e associazioni</legend>
          {draft.sources.length > 1 ? (
            <label className="users-clone-toggle users-clone-toggle--all">
              <input
                type="checkbox"
                checked={allSourcesLinked}
                disabled={cloning || validating}
                onChange={(event) => setAllSourceLinks(event.target.checked)}
              />
              Associa tutte le copie al gruppo sorgente
            </label>
          ) : null}
          <div className="users-clone-source-list">
            {draft.sources.map((source, index) => <div key={`${source.user.server_id}:${source.user.user_id}`} className="users-clone-source"><div><strong>{source.user.name}</strong><ServerIdentity name={source.user.server_alias || source.user.server_name} icon={source.user.server_icon} color={source.user.server_icon_color} iconStyle={source.user.server_icon_style} size={12} /></div><label><span>Nome copia</span><input value={source.newUsername} disabled={cloning || validating} onChange={(event) => updateSource(index, { newUsername: event.target.value })} /></label><label className="users-clone-toggle"><input type="checkbox" checked={source.linkGroup} disabled={cloning || validating} onChange={(event) => updateSource(index, { linkGroup: event.target.checked })} />Associa al gruppo sorgente</label></div>)}
          </div>
        </fieldset>
        <fieldset>
          <legend>Dati da copiare</legend>
          <div className="users-clone-options">
            <Toggle label="Impostazioni Emby" checked={draft.syncConfig} disabled={cloning || validating} onChange={(syncConfig) => setDraft((current) => ({ ...current, syncConfig }))} />
            <Toggle label="Stato visto" checked={draft.syncPlaystate} disabled={cloning || validating} onChange={(syncPlaystate) => setDraft((current) => ({ ...current, syncPlaystate }))} />
            <Toggle label="Riprendi" checked={draft.syncResume} disabled={!draft.syncPlaystate || cloning || validating} onChange={(syncResume) => setDraft((current) => ({ ...current, syncResume }))} />
            <Toggle label="Accesso librerie" checked={draft.syncLibraryAccess} disabled={cloning || validating} onChange={(syncLibraryAccess) => setDraft((current) => ({ ...current, syncLibraryAccess }))} />
            <Toggle label="Preferiti" checked={draft.syncFavorites} disabled={cloning || validating} onChange={(syncFavorites) => setDraft((current) => ({ ...current, syncFavorites }))} />
            <Toggle label="Playlist" checked={draft.syncPlaylists} disabled={cloning || validating} onChange={(syncPlaylists) => setDraft((current) => ({ ...current, syncPlaylists }))} />
          </div>
          <div className="users-clone-config-categories" aria-disabled={!draft.syncConfig || cloning || validating}>
            <strong>Categorie impostazioni</strong>
            {userConfigurationCategories.map((category) => <label key={category.id}><input type="checkbox" checked={draft.configCategories.includes(category.id)} disabled={!draft.syncConfig || cloning || validating} onChange={() => toggleConfigCategory(category.id)} />{category.label}</label>)}
          </div>
        </fieldset>
        <p className="users-dialog-summary">{operationCount === 1 ? "1 operazione verrà eseguita." : `${operationCount} operazioni verranno eseguite.`}</p>
        <footer>
          <Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={cloning || validating}>Annulla</Button>
          <Button type="submit" variant="primary" disabled={!operationCount || cloning || validating}>{validating ? "Verifica nomi..." : cloning ? "Clonazione..." : users.length === 1 ? "Clona utente" : "Clona utenti"}</Button>
        </footer>
        </form>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

function Toggle({ label, checked, disabled = false, onChange }: { label: string; checked: boolean; disabled?: boolean; onChange: (next: boolean) => void }) {
  return <label className="users-clone-toggle"><input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />{label}</label>;
}

export { CloneUserDialog };
