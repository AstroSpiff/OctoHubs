import { KeyRound, LayoutPanelLeft, LayoutPanelTop, ShieldCheck, UserRound } from "@/components/ui/icons";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { accountRoleLabels, formatAccountDate, navigationPreferenceLabels } from "@/features/account-management/account-presentation";
import type { CurrentOctoHubsAccount } from "@/features/account-management/types";

type AccountProfilePanelProps = {
  account?: CurrentOctoHubsAccount;
  error?: string;
  saving: boolean;
  onChangePassword: (input: { currentPassword: string; newPassword: string }) => Promise<unknown>;
};

function AccountProfilePanel({ account, error, saving, onChangePassword }: AccountProfilePanelProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [repeatPassword, setRepeatPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");

  if (!account) return <div className="loading-state">Caricamento account...</div>;
  const navigation = navigationPreferenceLabels(account.preferences);

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setFormError("");
    if (newPassword !== repeatPassword) {
      setFormError("La conferma password non corrisponde.");
      return;
    }
    try {
      await onChangePassword({ currentPassword, newPassword });
      setCurrentPassword("");
      setNewPassword("");
      setRepeatPassword("");
      setNotice("Password aggiornata.");
    } catch (requestError) {
      setFormError(requestError instanceof Error ? requestError.message : "Impossibile aggiornare la password.");
    }
  }

  return (
    <section className="account-profile-panel" aria-labelledby="account-profile-title">
      <header>
        <div>
          <h3 id="account-profile-title" className="contextual-heading" title="Accesso personale">Il mio account</h3>
          <p>I dati operativi di OctoHubs restano condivisi. Qui gestisci soltanto credenziali e preferenze personali dell&apos;interfaccia.</p>
        </div>
        <span className="account-role-badge"><ShieldCheck size={15} aria-hidden="true" />{accountRoleLabels[account.role]}</span>
      </header>

      <dl className="account-profile-details">
        <div><dt><UserRound size={15} aria-hidden="true" />Username</dt><dd>{account.username}</dd></div>
        <div><dt>Email</dt><dd>{account.email || "Non impostata"}</dd></div>
        <div><dt>Ultimo accesso</dt><dd>{formatAccountDate(account.last_login)}</dd></div>
        <div><dt>Account creato</dt><dd>{formatAccountDate(account.created_at)}</dd></div>
      </dl>

      <section className="account-preference-summary" aria-label="Preferenze personali dell'interfaccia">
        <div><LayoutPanelTop size={16} aria-hidden="true" /><span><strong>Menu principale</strong><small>{navigation.primary}</small></span></div>
        <div><LayoutPanelLeft size={16} aria-hidden="true" /><span><strong>Menu secondario</strong><small>{navigation.secondary}</small></span></div>
      </section>

      <form className="account-password-form" onSubmit={(event) => void submitPassword(event)}>
        <header><div><KeyRound size={16} aria-hidden="true" /><strong>Modifica password</strong></div><small>Minimo 8 caratteri.</small></header>
        <div>
          <label>Password attuale<input type="password" autoComplete="current-password" value={currentPassword} disabled={saving} onChange={(event) => setCurrentPassword(event.target.value)} required /></label>
          <label>Nuova password<input type="password" autoComplete="new-password" minLength={8} value={newPassword} disabled={saving} onChange={(event) => setNewPassword(event.target.value)} required /></label>
          <label>Conferma password<input type="password" autoComplete="new-password" minLength={8} value={repeatPassword} disabled={saving} onChange={(event) => setRepeatPassword(event.target.value)} required /></label>
        </div>
        {error || formError ? <p className="account-form-feedback is-error" role="alert">{formError || error}</p> : null}
        {notice ? <p className="account-form-feedback is-success" role="status">{notice}</p> : null}
        <footer><Button type="submit" variant="secondary" disabled={saving || !currentPassword || !newPassword || !repeatPassword}>{saving ? "Aggiornamento..." : "Aggiorna password"}</Button></footer>
      </form>
    </section>
  );
}

export { AccountProfilePanel };
