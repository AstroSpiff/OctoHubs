import { Eye, EyeOff } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { getPasswordInfo } from "@/features/users/api";
import { formatUserTime } from "@/features/users/presentation";
import { useDirtyChange } from "@/lib/use-dirty-change";
import type { PasswordTarget } from "@/features/users/types";

type PasswordDialogProps = {
  target: PasswordTarget | null;
  saving: boolean;
  onClose: () => void;
  onSave: (password: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function PasswordDialog({ target, saving, onClose, onSave, onDirtyChange }: PasswordDialogProps) {
  const confirmation = useConfirmationDialog();
  const [password, setPassword] = useState("");
  const [savedPassword, setSavedPassword] = useState("");
  const [hasSavedPassword, setHasSavedPassword] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [loadedTargetKey, setLoadedTargetKey] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const targetKey = target
    ? target.scope === "group"
      ? `group:${target.groupId}`
      : `user:${target.serverId}:${target.userId}`
    : null;

  useEffect(() => {
    if (!target) return undefined;
    let active = true;
    setLoading(true);
    setError("");
    setRevealed(false);
    setPassword("");
    setSavedPassword("");
    setHasSavedPassword(false);
    setUpdatedAt(null);
    setLoadedTargetKey(null);

    getPasswordInfo(target)
      .then((result) => {
        if (!active) return;
        const nextPassword = result.password || "";
        setPassword(nextPassword);
        setSavedPassword(nextPassword);
        setHasSavedPassword(result.saved);
        setUpdatedAt(result.updated_at || null);
        setLoadedTargetKey(targetKey);
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [target, targetKey]);

  const dirty = targetKey === loadedTargetKey && !loading && password !== savedPassword;
  useDirtyChange(Boolean(target), dirty, onDirtyChange);

  if (!target) return null;
  const statusDetail = target.scope === "group"
    ? target.mismatchCount
      ? `${target.mismatchCount} ${target.mismatchCount === 1 ? "utente non allineato" : "utenti non allineati"}`
      : ""
    : hasSavedPassword && target.mismatch
      ? "Non allineata al gruppo"
      : !hasSavedPassword && target.hasEmbyPassword !== undefined
        ? `Emby: ${target.hasEmbyPassword ? "presente" : "assente"}`
        : "";

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSave(password);
  }

  async function requestReset() {
    if (loading || saving) return;
    const currentTarget = target;
    if (!currentTarget) return;
    const confirmed = await confirmation.confirm({
      title: "Reimposta password",
      description: currentTarget.scope === "group"
        ? "La password salvata verrà rimossa e azzerata per tutti gli utenti del gruppo."
        : "La password salvata verrà rimossa e azzerata su Emby per questo utente.",
      confirmLabel: "Reimposta password",
      tone: "danger",
    });
    if (confirmed) onSave("");
  }

  async function requestApplyToGroup() {
    const currentTarget = target;
    if (currentTarget?.scope !== "group" || loading || saving || !savedPassword) return;
    const confirmed = await confirmation.confirm({
      title: "Applica password al gruppo",
      description: "La password salvata verrà applicata a tutti gli utenti del gruppo per riallinearli.",
      confirmLabel: "Applica a tutti",
    });
    if (confirmed) onSave(savedPassword);
  }

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Password non aggiornata",
      description: "Chiudere e perdere la password inserita?",
      confirmLabel: "Abbandona modifiche",
      tone: "danger",
    });
    if (confirmed) onClose();
  }

  return (
    <>
    <DialogBackdrop
      className="users-dialog-backdrop"
      dismissible={!saving}
      onDismiss={() => void requestClose()}
    >
      <form
        className="users-compact-dialog"
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="password-dialog-title"
      >
        <header>
          <h2 id="password-dialog-title" className="contextual-heading" title={`Password ${target.scope === "group" ? "gruppo" : "utente"}`}>{target.name}</h2>
        </header>
        {error ? <p className="users-dialog-error" role="alert">{error}</p> : null}
        <p className="users-password-status" role="status">
          {loading ? "Verifica password salvata..." : hasSavedPassword ? "Password salvata" : "Password non salvata"}
          {statusDetail ? ` · ${statusDetail}` : ""}
          {updatedAt ? <small>Ultimo aggiornamento: {formatUserTime(updatedAt)}</small> : null}
        </p>
        <label>
          Password
          <div className="users-password-input">
            <input
              autoFocus
              type={revealed ? "text" : "password"}
              value={password}
              disabled={loading || saving}
              onChange={(event) => setPassword(event.target.value)}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              title={revealed ? "Nascondi password" : "Mostra password"}
              aria-label={revealed ? "Nascondi password" : "Mostra password"}
              onClick={() => setRevealed((current) => !current)}
              disabled={loading || saving}
            >
              {revealed ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
            </Button>
          </div>
          <small>Lascia vuoto per rimuovere la password.</small>
        </label>
        <footer className="users-password-dialog-actions">
          <Button type="button" variant="ghost" className="users-password-reset" onClick={() => void requestReset()} disabled={loading || saving}>
            Reimposta
          </Button>
          <div>
            <Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={saving}>
              Annulla
            </Button>
            {target.scope === "group" && target.mismatchCount && hasSavedPassword && savedPassword ? <Button type="button" variant="secondary" onClick={() => void requestApplyToGroup()} disabled={loading || saving}>
              Applica a tutti
            </Button> : null}
            <Button type="submit" variant="primary" disabled={loading || saving || !dirty}>
              {saving ? "Salvataggio..." : "Aggiorna password"}
            </Button>
          </div>
        </footer>
      </form>
    </DialogBackdrop>
    {confirmation.dialog}
    </>
  );
}

export { PasswordDialog };
