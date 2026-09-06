import { CheckCircle2, Pencil, Plus, RefreshCw, Trash2, XCircle } from "@/components/ui/icons";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import {
  telegramBotDraftIsDirty,
  telegramChatDraftIsDirty,
} from "@/features/configuration/telegram-draft";
import type { TelegramBot, TelegramChat } from "@/features/configuration/types";

type ResourceRunner = (action:
  | { action: "bot.save"; data: { id?: string; alias: string; token?: string } }
  | { action: "bot.verify" | "bot.remove"; data: { id: string } }
  | { action: "chat.save"; data: { id?: string; kind: "group" | "channel"; alias: string; chat_id: string } }
  | { action: "chat.verify"; data: { id: string; kind: "group" | "channel"; bot_id?: string } }
  | { action: "chat.remove"; data: { id: string; kind: "group" | "channel" } },
) => Promise<unknown>;

function TelegramBotResourcePanel({
  bots,
  busy,
  onAction,
  onDirtyChange,
}: {
  bots: TelegramBot[];
  busy: boolean;
  onAction: ResourceRunner;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const confirmation = useConfirmationDialog();
  const [editing, setEditing] = useState<TelegramBot | null>(null);
  const [alias, setAlias] = useState("");
  const [token, setToken] = useState("");
  const dirty = telegramBotDraftIsDirty(editing, { alias, token });

  useEffect(() => {
    setAlias(editing?.alias || "");
    setToken("");
  }, [editing]);

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  async function discardDraft(description: string) {
    if (!dirty) return true;
    return confirmation.confirm({
      title: "Modifiche non salvate",
      description,
      confirmLabel: "Scarta modifiche",
      tone: "danger",
    });
  }

  async function openEditor(next: TelegramBot) {
    if (!await discardDraft("Aprire un'altra risorsa e perdere le modifiche in corso?")) return;
    setEditing(next);
  }

  async function cancelEditor() {
    if (!await discardDraft("Annullare e perdere le modifiche in corso?")) return;
    setEditing(null);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onAction({ action: "bot.save", data: { id: editing?.id, alias, token } })
      .then(() => setEditing(null))
      .catch(() => undefined);
  }

  async function removeBot(bot: TelegramBot) {
    const label = bot.alias || bot.original_name || bot.username || "questo bot Telegram";
    if (!await confirmation.confirm({
      title: "Rimuovi bot Telegram",
      description: `Rimuovere ${label}?`,
      confirmLabel: "Rimuovi bot",
      tone: "danger",
    })) return;
    void onAction({ action: "bot.remove", data: { id: bot.id } }).catch(() => undefined);
  }

  return <section className="telegram-resource-panel">
    <header>
      <div><h3>Bot</h3><p>Il token viene usato solo per salvare o sostituire il bot.</p></div>
      <Button type="button" requiresWriteAccess variant="secondary" size="compact" onClick={() => void openEditor({} as TelegramBot)} disabled={busy}>
        <Plus size={15} aria-hidden="true" />Aggiungi
      </Button>
    </header>
    {editing ? <form className="telegram-resource-form" onSubmit={submit} aria-busy={busy}>
      <label>Token bot<input type="password" required={!editing.id} disabled={busy} placeholder={editing.token_configured ? "Lascia vuoto per conservarlo" : "123456:ABC-DEF..."} value={token} onChange={(event) => setToken(event.target.value)} /></label>
      <label>Alias<input type="text" disabled={busy} placeholder="Bot notifiche" value={alias} onChange={(event) => setAlias(event.target.value)} /></label>
      <footer><Button type="button" variant="ghost" size="compact" onClick={() => void cancelEditor()} disabled={busy}>Annulla</Button><Button type="submit" variant="primary" size="compact" disabled={busy}>{editing.id ? "Aggiorna" : "Salva"}</Button></footer>
    </form> : null}
    <div className="telegram-resource-list">
      {bots.length ? bots.map((bot) => <article key={bot.id} className="telegram-resource-row">
        <ResourceIdentity title={bot.alias || bot.original_name || bot.username || "Bot Telegram"} subtitle={bot.username ? `@${bot.username}` : bot.token_configured ? "Token configurato" : "Token mancante"} verified={bot.verified} error={bot.last_error} />
        <div className="telegram-resource-actions">
          <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Verifica bot" aria-label="Verifica bot" onClick={() => void onAction({ action: "bot.verify", data: { id: bot.id } }).catch(() => undefined)} disabled={busy}><RefreshCw size={15} aria-hidden="true" /></Button>
          <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Modifica bot" aria-label="Modifica bot" onClick={() => void openEditor(bot)} disabled={busy}><Pencil size={15} aria-hidden="true" /></Button>
          <Button type="button" requiresWriteAccess variant="ghost" size="icon" className="danger-action" title="Rimuovi bot" aria-label="Rimuovi bot" onClick={() => void removeBot(bot)} disabled={busy}><Trash2 size={15} aria-hidden="true" /></Button>
        </div>
      </article>) : <p className="telegram-empty">Nessun bot configurato.</p>}
    </div>
    {confirmation.dialog}
  </section>;
}

function TelegramChatResourcePanel({
  kind,
  entries,
  busy,
  onAction,
  onDirtyChange,
}: {
  kind: "group" | "channel";
  entries: TelegramChat[];
  busy: boolean;
  onAction: ResourceRunner;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const confirmation = useConfirmationDialog();
  const [editing, setEditing] = useState<TelegramChat | null>(null);
  const [alias, setAlias] = useState("");
  const [chatId, setChatId] = useState("");
  const title = kind === "group" ? "Gruppi" : "Canali";
  const dirty = telegramChatDraftIsDirty(editing, { alias, chatId });

  useEffect(() => {
    setAlias(editing?.alias || "");
    setChatId(editing?.chat_id || "");
  }, [editing]);

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  async function discardDraft(description: string) {
    if (!dirty) return true;
    return confirmation.confirm({ title: "Modifiche non salvate", description, confirmLabel: "Scarta modifiche", tone: "danger" });
  }

  async function openEditor(next: TelegramChat) {
    if (!await discardDraft("Aprire un'altra risorsa e perdere le modifiche in corso?")) return;
    setEditing(next);
  }

  async function cancelEditor() {
    if (!await discardDraft("Annullare e perdere le modifiche in corso?")) return;
    setEditing(null);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onAction({ action: "chat.save", data: { id: editing?.id, kind, alias, chat_id: chatId } })
      .then(() => setEditing(null))
      .catch(() => undefined);
  }

  async function removeChat(entry: TelegramChat) {
    const label = entry.alias || entry.original_name || entry.chat_id || (kind === "group" ? "questo gruppo" : "questo canale");
    if (!await confirmation.confirm({ title: `Rimuovi ${kind === "group" ? "gruppo" : "canale"}`, description: `Rimuovere ${label}?`, confirmLabel: "Rimuovi", tone: "danger" })) return;
    void onAction({ action: "chat.remove", data: { id: entry.id, kind } }).catch(() => undefined);
  }

  return <section className="telegram-resource-panel">
    <header>
      <div><h3>{title}</h3><p>Destinazioni assegnabili alle preconfigurazioni.</p></div>
      <Button type="button" requiresWriteAccess variant="secondary" size="compact" onClick={() => void openEditor({} as TelegramChat)} disabled={busy}><Plus size={15} aria-hidden="true" />Aggiungi</Button>
    </header>
    {editing ? <form className="telegram-resource-form" onSubmit={submit} aria-busy={busy}>
      <label>Chat ID<input type="text" required disabled={busy} placeholder="-1001234567890" value={chatId} onChange={(event) => setChatId(event.target.value)} /></label>
      <label>Alias<input type="text" disabled={busy} placeholder={kind === "group" ? "Gruppo notifiche" : "Canale notifiche"} value={alias} onChange={(event) => setAlias(event.target.value)} /></label>
      <footer><Button type="button" variant="ghost" size="compact" onClick={() => void cancelEditor()} disabled={busy}>Annulla</Button><Button type="submit" variant="primary" size="compact" disabled={busy}>{editing.id ? "Aggiorna" : "Salva"}</Button></footer>
    </form> : null}
    <div className="telegram-resource-list">
      {entries.length ? entries.map((entry) => <article key={entry.id} className="telegram-resource-row">
        <ResourceIdentity title={entry.alias || entry.original_name || entry.chat_id} subtitle={entry.original_name ? entry.chat_id : "In attesa di verifica"} verified={entry.verified} error={entry.last_error} />
        <div className="telegram-resource-actions">
          <Button type="button" requiresWriteAccess variant="ghost" size="icon" title={`Verifica ${kind === "group" ? "gruppo" : "canale"}`} aria-label={`Verifica ${kind === "group" ? "gruppo" : "canale"}`} onClick={() => void onAction({ action: "chat.verify", data: { id: entry.id, kind } }).catch(() => undefined)} disabled={busy}><RefreshCw size={15} aria-hidden="true" /></Button>
          <Button type="button" requiresWriteAccess variant="ghost" size="icon" title={`Modifica ${kind === "group" ? "gruppo" : "canale"}`} aria-label={`Modifica ${kind === "group" ? "gruppo" : "canale"}`} onClick={() => void openEditor(entry)} disabled={busy}><Pencil size={15} aria-hidden="true" /></Button>
          <Button type="button" requiresWriteAccess variant="ghost" size="icon" className="danger-action" title={`Rimuovi ${kind === "group" ? "gruppo" : "canale"}`} aria-label={`Rimuovi ${kind === "group" ? "gruppo" : "canale"}`} onClick={() => void removeChat(entry)} disabled={busy}><Trash2 size={15} aria-hidden="true" /></Button>
        </div>
      </article>) : <p className="telegram-empty">Nessun {kind === "group" ? "gruppo" : "canale"} configurato.</p>}
    </div>
    {confirmation.dialog}
  </section>;
}

function ResourceIdentity({ title, subtitle, verified, error }: { title: string; subtitle: string; verified: boolean; error: string }) {
  const verificationLabel = verified ? "Verificato" : error ? "Verifica non riuscita" : "Non verificato";
  return <div className="telegram-resource-identity">
    <span role="status" aria-label={verificationLabel} title={verificationLabel} className={verified ? "telegram-verification telegram-verification--ok" : "telegram-verification telegram-verification--unknown"}>{verified ? <CheckCircle2 size={16} aria-hidden="true" /> : <XCircle size={16} aria-hidden="true" />}<span className="sr-only">{verificationLabel}</span></span>
    <div><strong>{title}</strong><small title={error || subtitle}>{error || subtitle}</small></div>
  </div>;
}

export { TelegramBotResourcePanel, TelegramChatResourcePanel };
