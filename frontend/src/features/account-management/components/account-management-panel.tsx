import { Pencil, Plus, Power, Trash2, UserRound } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { accountRoleLabels, formatAccountDate } from "@/features/account-management/account-presentation";
import { AccountEditorDialog } from "@/features/account-management/components/account-editor-dialog";
import type { CreateOctoHubsAccountInput, OctoHubsAccount, UpdateOctoHubsAccountInput } from "@/features/account-management/types";

type AccountManagementPanelProps = {
  accounts: OctoHubsAccount[];
  busyAccountIds: ReadonlySet<string>;
  creating: boolean;
  createError?: string;
  currentAccountId: number;
  loading: boolean;
  onCreate: (input: CreateOctoHubsAccountInput) => Promise<unknown>;
  onDelete: (accountId: number) => Promise<unknown>;
  onResetErrors: (accountId?: number) => void;
  onUpdate: (accountId: number, input: UpdateOctoHubsAccountInput) => Promise<unknown>;
  operationErrors: Readonly<Record<string, string>>;
};

function AccountManagementPanel({ accounts, busyAccountIds, createError, creating, currentAccountId, loading, onCreate, onDelete, onResetErrors, onUpdate, operationErrors }: AccountManagementPanelProps) {
  const confirmation = useConfirmationDialog();
  const [editing, setEditing] = useState<OctoHubsAccount | null>(null);
  const [creatingAccount, setCreatingAccount] = useState(false);

  async function requestDelete(account: OctoHubsAccount) {
    onResetErrors(account.id);
    const confirmed = await confirmation.confirm({
      title: `Eliminare ${account.username}?`,
      description: "L'account non potrà più accedere a OctoHubs. I dati operativi condivisi non verranno modificati.",
      confirmLabel: "Elimina account",
      tone: "danger",
    });
    if (!confirmed) return;
    await onDelete(account.id);
  }

  return (
    <section className="account-management-panel" aria-labelledby="account-management-title">
      <header>
        <div><h3 id="account-management-title" className="contextual-heading" title="Amministrazione">Gestione accessi</h3><p>Crea e governa gli accessi all&apos;applicazione. Tutti vedono gli stessi server, dati e notifiche dell&apos;istanza.</p></div>
        <Button type="button" variant="primary" size="compact" onClick={() => { onResetErrors(); setCreatingAccount(true); }}><Plus size={16} aria-hidden="true" />Crea account</Button>
      </header>
      {loading ? <div className="loading-state">Caricamento accessi OctoHubs...</div> : null}
      {!loading ? <div className="account-management-list">
        {accounts.map((account) => <AccountRow key={account.id} account={account} busy={creating || busyAccountIds.has(String(account.id))} current={account.id === currentAccountId} error={operationErrors[String(account.id)]} onEdit={() => { onResetErrors(account.id); setEditing(account); }} onToggleActive={() => { onResetErrors(account.id); void onUpdate(account.id, { is_active: !account.is_active }).catch(() => undefined); }} onDelete={() => void requestDelete(account).catch(() => undefined)} />)}
      </div> : null}
      {!loading && !accounts.length ? <p className="account-empty">Non ci sono ancora altri accessi configurati.</p> : null}
      <AccountEditorDialog open={creatingAccount || Boolean(editing)} account={editing} busy={creating || Boolean(editing && busyAccountIds.has(String(editing.id)))} error={creatingAccount ? createError : editing ? operationErrors[String(editing.id)] : undefined} onClose={() => { onResetErrors(); setCreatingAccount(false); setEditing(null); }} onCreate={onCreate} onUpdate={onUpdate} />
      {confirmation.dialog}
    </section>
  );
}

function AccountRow({ account, busy, current, error, onDelete, onEdit, onToggleActive }: { account: OctoHubsAccount; busy: boolean; current: boolean; error?: string; onDelete: () => void; onEdit: () => void; onToggleActive: () => void }) {
  return (
    <article className={`account-management-row${account.is_active ? "" : " is-inactive"}`}>
      <div className="account-row-avatar" aria-hidden="true">{account.username.slice(0, 1).toUpperCase() || <UserRound size={16} />}</div>
      <div className="account-row-identity"><strong>{account.username}{current ? <small>Tu</small> : null}</strong><span>{account.email || "Email non impostata"}</span></div>
      <div className="account-row-meta"><span className={`account-role-badge account-role-badge--${account.role}`}>{accountRoleLabels[account.role]}</span><small>{account.is_active ? `Ultimo accesso ${formatAccountDate(account.last_login)}` : "Accesso disabilitato"}</small></div>
      <div className="account-row-actions">
        <Button type="button" variant="ghost" size="icon" title={account.is_active ? "Disabilita accesso" : "Riabilita accesso"} aria-label={`${account.is_active ? "Disabilita" : "Riabilita"} ${account.username}`} onClick={onToggleActive} disabled={busy || current}><Power size={16} aria-hidden="true" /></Button>
        <Button type="button" variant="ghost" size="icon" title="Modifica account" aria-label={`Modifica ${account.username}`} onClick={onEdit} disabled={busy}><Pencil size={16} aria-hidden="true" /></Button>
        <Button type="button" variant="ghost" size="icon" className="account-delete-action" title="Elimina account" aria-label={`Elimina ${account.username}`} onClick={onDelete} disabled={busy || current}><Trash2 size={16} aria-hidden="true" /></Button>
      </div>
      {error ? <div className="account-row-error inline-alert inline-alert--error" role="alert">{error}</div> : null}
    </article>
  );
}

export { AccountManagementPanel };
