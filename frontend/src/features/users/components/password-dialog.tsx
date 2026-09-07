import { Eye, EyeOff } from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { getPasswordInfo } from "@/features/users/api";
import { formatUserTime } from "@/features/users/presentation";
import { useDirtyChange } from "@/lib/use-dirty-change";
import { errorMessage, type AuthoritativeSnapshot } from "@/lib/authoritative-snapshot";
import type { PasswordTarget } from "@/features/users/types";

type PasswordDialogProps = {
  target: PasswordTarget | null;
  saving: boolean;
  mutationError?: string;
  onClose: () => void;
  onSave: (password: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function PasswordDialog({ target, saving, mutationError, onClose, onSave, onDirtyChange }: PasswordDialogProps) {
  const confirmation = useConfirmationDialog();
  const [password, setPassword] = useState("");
  const [savedPassword, setSavedPassword] = useState("");
  const [snapshot, setSnapshot] = useState<
    AuthoritativeSnapshot<Awaited<ReturnType<typeof getPasswordInfo>>> & {
      targetKey: string;
    }
  >({ status: "pending", targetKey: "" });
  const [loadVersion, setLoadVersion] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const targetKey = target
    ? target.scope === "group"
      ? `group:${target.groupId}`
      : `user:${target.serverId}:${target.userId}`
    : null;

  useEffect(() => {
    if (!target) {
      setPassword("");
      setSavedPassword("");
      setSnapshot({ status: "pending", targetKey: "" });
      setRevealed(false);
      return undefined;
    }
    let active = true;
    setSnapshot({ status: "pending", targetKey: targetKey || "" });
    setRevealed(false);
    setPassword("");
    setSavedPassword("");

    getPasswordInfo(target)
      .then((result) => {
        if (!active) return;
        const nextPassword = result.password || "";
        setPassword(nextPassword);
        setSavedPassword(nextPassword);
        setSnapshot({
          status: "success",
          targetKey: targetKey || "",
          data: result,
        });
      })
      .catch((reason: unknown) => {
        if (active) {
          setSnapshot({
            status: "error",
            targetKey: targetKey || "",
            error: errorMessage(reason, "Impossibile verificare la password salvata."),
          });
        }
      });

    return () => {
      active = false;
    };
  }, [loadVersion, target, targetKey]);

  const currentSnapshot = snapshot.targetKey === targetKey ? snapshot : undefined;
  const authoritative = currentSnapshot?.status === "success"
    ? currentSnapshot.data
    : undefined;
  const authorityRef = useRef({ authoritative, targetKey });
  authorityRef.current = { authoritative, targetKey };
  const loading = !currentSnapshot || currentSnapshot.status === "pending";
  const hasSavedPassword = authoritative?.saved;
  const updatedAt = authoritative?.updated_at || null;
  const dirty = Boolean(authoritative && password !== savedPassword);
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
    if (!authoritative || saving || !dirty) return;
    onSave(password);
  }

  async function requestReset() {
    if (!authoritative || saving) return;
    const currentTarget = target;
    const currentTargetKey = targetKey;
    if (!currentTarget) return;
    const confirmed = await confirmation.confirm({
      title: "Reimposta password",
      description: currentTarget.scope === "group"
        ? "La password salvata verrà rimossa e azzerata per tutti gli utenti del gruppo."
        : "La password salvata verrà rimossa e azzerata su Emby per questo utente.",
      confirmLabel: "Reimposta password",
      tone: "danger",
    });
    const currentAuthority = authorityRef.current;
    if (
      confirmed
      && currentAuthority.targetKey === currentTargetKey
      && currentAuthority.authoritative
    ) onSave("");
  }

  async function requestApplyToGroup() {
    const currentTarget = target;
    if (currentTarget?.scope !== "group" || !authoritative || saving || !savedPassword) return;
    const currentTargetKey = targetKey;
    const confirmed = await confirmation.confirm({
      title: "Applica password al gruppo",
      description: "La password salvata verrà applicata a tutti gli utenti del gruppo per riallinearli.",
      confirmLabel: "Applica a tutti",
    });
    const currentAuthority = authorityRef.current;
    if (
      confirmed
      && currentAuthority.targetKey === currentTargetKey
      && currentAuthority.authoritative
    ) onSave(savedPassword);
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
        {currentSnapshot?.status === "error" ? (
          <div className="users-dialog-error" role="alert">
            <span>{currentSnapshot.error}</span>{" "}
            <Button type="button" variant="secondary" size="compact" onClick={() => setLoadVersion((version) => version + 1)}>
              Riprova verifica
            </Button>
          </div>
        ) : null}
        {mutationError ? <p className="users-dialog-error" role="alert">{mutationError}</p> : null}
        <p className="users-password-status" role="status">
          {loading
            ? "Verifica password salvata..."
            : currentSnapshot?.status === "error"
              ? "Stato password non disponibile."
              : hasSavedPassword
                ? "Password salvata"
                : "Password non salvata"}
          {statusDetail ? ` · ${statusDetail}` : ""}
          {updatedAt ? <small>Ultimo aggiornamento: {formatUserTime(updatedAt)}</small> : null}
        </p>
        <div className="users-password-field">
          <label htmlFor="users-password-value">Password</label>
          <div className="users-password-input">
            <input
              id="users-password-value"
              autoFocus
              type={revealed ? "text" : "password"}
              value={authoritative ? password : ""}
              disabled={!authoritative || saving}
              onChange={(event) => setPassword(event.target.value)}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              title={revealed ? "Nascondi password" : "Mostra password"}
              aria-label={revealed ? "Nascondi password" : "Mostra password"}
              onClick={() => setRevealed((current) => !current)}
              disabled={!authoritative || saving}
            >
              {revealed ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
            </Button>
          </div>
          <small>Lascia vuoto per rimuovere la password.</small>
        </div>
        <footer className="users-password-dialog-actions">
          <Button type="button" variant="ghost" className="users-password-reset" onClick={() => void requestReset()} disabled={!authoritative || saving}>
            Reimposta
          </Button>
          <div>
            <Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={saving}>
              Annulla
            </Button>
            {target.scope === "group" && target.mismatchCount && hasSavedPassword && savedPassword ? <Button type="button" variant="secondary" onClick={() => void requestApplyToGroup()} disabled={!authoritative || saving}>
              Applica a tutti
            </Button> : null}
            <Button type="submit" variant="primary" disabled={!authoritative || saving || !dirty}>
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
