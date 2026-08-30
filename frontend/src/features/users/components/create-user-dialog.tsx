import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { useDirtyChange } from "@/lib/use-dirty-change";
import { getSettingsPresets } from "@/features/user-settings/api";
import { ServerIdentity } from "@/features/users/components/server-identity";
import {
  createUserDraft,
  createUserDraftMatches,
  type CreateUserDraft,
} from "@/features/users/create-user-draft";
import type { EmbyUserServer } from "@/features/users/types";

type CreateUserDialogProps = {
  open: boolean;
  servers: EmbyUserServer[];
  creating: boolean;
  onClose: () => void;
  onCreate: (input: {
    username: string;
    password: string;
    serverIds: string[];
    linkGroup: boolean;
    presetId?: string | null;
  }) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function CreateUserDialog({
  open,
  servers,
  creating,
  onClose,
  onCreate,
  onDirtyChange,
}: CreateUserDialogProps) {
  const confirmation = useConfirmationDialog();
  const [draft, setDraft] = useState<CreateUserDraft>(() =>
    createUserDraft(servers),
  );
  const [baseline, setBaseline] = useState<CreateUserDraft>(() =>
    createUserDraft(servers),
  );
  const openedRef = useRef(false);
  const presets = useQuery({
    queryKey: ["user-settings-presets"],
    queryFn: getSettingsPresets,
    enabled: open,
  });

  useEffect(() => {
    if (!open) {
      openedRef.current = false;
      return;
    }
    if (openedRef.current) return;

    openedRef.current = true;
    const nextDraft = createUserDraft(servers);
    setDraft(nextDraft);
    setBaseline(nextDraft);
  }, [open, servers]);

  const dirty = !createUserDraftMatches(draft, baseline);
  useDirtyChange(open, dirty, onDirtyChange);

  if (!open) return null;

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.username.trim() || !draft.serverIds.length) return;
    onCreate({
      username: draft.username.trim(),
      password: draft.password,
      serverIds: draft.serverIds,
      linkGroup: draft.linkGroup,
      presetId: draft.presetId || null,
    });
  }

  function toggleServer(serverId: string) {
    setDraft((current) => ({
      ...current,
      serverIds: current.serverIds.includes(serverId)
        ? current.serverIds.filter((id) => id !== serverId)
        : [...current.serverIds, serverId],
    }));
  }

  async function requestClose() {
    if (creating) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Creazione utente non completata",
      description: "Chiudere e perdere i dati del nuovo utente?",
      confirmLabel: "Abbandona creazione",
      tone: "danger",
    });
    if (confirmed) onClose();
  }

  return (
    <>
      <DialogBackdrop
        className="users-dialog-backdrop"
        dismissible={!creating}
        onDismiss={() => void requestClose()}
      >
        <form
          className="users-create-dialog"
          onSubmit={submit}
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-user-title"
        >
          <header>
            <h2 id="create-user-title">Crea utente</h2>
          </header>

        <label>
          Nome utente
          <input
            autoFocus
            value={draft.username}
            disabled={creating}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                username: event.target.value,
              }))
            }
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={draft.password}
            disabled={creating}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                password: event.target.value,
              }))
            }
          />
        </label>
        <label>
          Impostazioni iniziali
          <select
            value={draft.presetId}
            disabled={creating || presets.isLoading}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                presetId: event.target.value,
              }))
            }
          >
            <option value="">Default Emby</option>
            {presets.data?.presets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label || preset.id}
              </option>
            ))}
          </select>
          <small>
            {presets.error
              ? "Preset non disponibili: verranno usate le impostazioni Emby."
              : "Un preset viene applicato subito dopo la creazione."}
          </small>
        </label>
        <fieldset disabled={creating}>
          <legend>Server</legend>
          {servers.map((server) => (
            <label key={server.id}>
              <input
                type="checkbox"
                checked={draft.serverIds.includes(server.id)}
                onChange={() => toggleServer(server.id)}
              />
              <ServerIdentity
                name={server.name}
                icon={server.icon}
                color={server.icon_color}
                iconStyle={server.icon_style}
              />
            </label>
          ))}
        </fieldset>
        <label className="users-dialog-switch">
          <input
            type="checkbox"
            checked={draft.linkGroup}
            disabled={creating}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                linkGroup: event.target.checked,
              }))
            }
          />
          Associa gli utenti creati
        </label>

          <footer>
            <Button
              type="button"
              variant="ghost"
              onClick={() => void requestClose()}
              disabled={creating}
            >
              Annulla
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={
                !draft.username.trim() || !draft.serverIds.length || creating
              }
            >
              Crea
            </Button>
          </footer>
        </form>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

export { CreateUserDialog };
