import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { accountRoleLabels } from "@/features/account-management/account-presentation";
import type { AccountRole, CreateOctoHubsAccountInput, OctoHubsAccount, UpdateOctoHubsAccountInput } from "@/features/account-management/types";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";

type AccountEditorDialogProps = {
  account?: OctoHubsAccount | null;
  busy: boolean;
  error?: string;
  onClose: () => void;
  onCreate: (input: CreateOctoHubsAccountInput) => Promise<unknown>;
  onUpdate: (accountId: number, input: UpdateOctoHubsAccountInput) => Promise<unknown>;
  open: boolean;
};

function AccountEditorDialog({ account, busy, error, onClose, onCreate, onUpdate, open }: AccountEditorDialogProps) {
  const creating = !account;
  const confirmation = useConfirmationDialog();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<AccountRole>("user");
  const [isActive, setIsActive] = useState(true);
  const [password, setPassword] = useState("");
  const [repeatPassword, setRepeatPassword] = useState("");
  const [formError, setFormError] = useState("");

  useEffect(() => {
    if (!open) {
      setUsername("");
      setEmail("");
      setRole("user");
      setIsActive(true);
      setPassword("");
      setRepeatPassword("");
      setFormError("");
      return;
    }
    setUsername(account?.username || "");
    setEmail(account?.email || "");
    setRole(account?.role || "user");
    setIsActive(account?.is_active ?? true);
    setPassword("");
    setRepeatPassword("");
    setFormError("");
  }, [account, open]);

  const dirty = open && (creating
    ? Boolean(username || email || password || repeatPassword || role !== "user" || !isActive)
    : email !== (account.email || "")
      || role !== account.role
      || isActive !== account.is_active
      || Boolean(password || repeatPassword));
  useBeforeUnloadWarning(dirty);

  if (!open) return null;

  async function requestClose() {
    if (busy) return;
    if (dirty && !(await confirmation.confirm({
      title: "Modifiche non salvate",
      description: "Chiudere il dialogo e perdere le modifiche all’account?",
      confirmLabel: "Abbandona modifiche",
      tone: "danger",
    }))) return;
    onClose();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    if (password !== repeatPassword) {
      setFormError("La conferma password non corrisponde.");
      return;
    }
    try {
      if (creating) {
        await onCreate({ username: username.trim(), email: email.trim(), password, role });
      } else {
        await onUpdate(account.id, {
          email: email.trim(),
          role,
          is_active: isActive,
          ...(password ? { password } : {}),
        });
      }
      onClose();
    } catch (requestError) {
      setFormError(requestError instanceof Error ? requestError.message : "Impossibile salvare l'account.");
    }
  }

  return (
    <>
    <DialogBackdrop className="account-dialog-backdrop" dismissible={!busy} onDismiss={() => void requestClose()}>
      <form className="account-editor-dialog" onSubmit={(event) => void submit(event)} role="dialog" aria-modal="true" aria-labelledby="account-editor-title">
        <header><div><h2 id="account-editor-title" className="contextual-heading" title="Accesso OctoHubs">{creating ? "Crea account" : `Modifica ${account.username}`}</h2></div></header>
        {creating ? <label>Username<input autoFocus autoComplete="username" minLength={3} maxLength={80} pattern="[A-Za-z0-9._-]+" value={username} disabled={busy} onChange={(event) => setUsername(event.target.value)} required /><small>Lettere, numeri, punto, trattino e underscore.</small></label> : <div className="account-editor-username"><span>Username</span><strong>{account.username}</strong></div>}
        <label>Email<input type="email" autoComplete="email" value={email} disabled={busy} onChange={(event) => setEmail(event.target.value)} placeholder="Facoltativa" /></label>
        <label>Ruolo<select value={role} disabled={busy} onChange={(event) => setRole(event.target.value as AccountRole)}>{(Object.keys(accountRoleLabels) as AccountRole[]).map((value) => <option key={value} value={value}>{accountRoleLabels[value]}</option>)}</select><small>{role === "admin" ? "Gestisce accessi e tutte le configurazioni." : role === "user" ? "Può lavorare sui dati e sulle configurazioni condivise." : "Può consultare dati e stato senza modificarli."}</small></label>
        {!creating ? <label className="account-editor-switch"><input type="checkbox" checked={isActive} disabled={busy} onChange={(event) => setIsActive(event.target.checked)} />Account attivo</label> : null}
        <fieldset disabled={busy}><legend>{creating ? "Password" : "Reimposta password"}</legend><label>{creating ? "Password" : "Nuova password (facoltativa)"}<input type="password" autoComplete="new-password" minLength={password ? 8 : undefined} value={password} onChange={(event) => setPassword(event.target.value)} required={creating} /></label><label>Conferma password<input type="password" autoComplete="new-password" minLength={repeatPassword ? 8 : undefined} value={repeatPassword} onChange={(event) => setRepeatPassword(event.target.value)} required={creating || Boolean(password)} /></label></fieldset>
        {error || formError ? <p className="account-form-feedback is-error" role="alert">{formError || error}</p> : null}
        <footer><Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={busy}>Annulla</Button><Button type="submit" variant="primary" disabled={busy || (creating && (!username.trim() || password.length < 8 || repeatPassword.length < 8))}>{busy ? "Salvataggio..." : creating ? "Crea account" : "Salva modifiche"}</Button></footer>
      </form>
    </DialogBackdrop>
    {confirmation.dialog}
    </>
  );
}

export { AccountEditorDialog };
