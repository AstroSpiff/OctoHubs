import { Pencil, Plus, Trash2 } from "@/components/ui/icons";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { TelegramPresetDestinationStatus } from "@/features/configuration/components/telegram-preset-destination-status";
import { telegramPresetDraftIsDirty } from "@/features/configuration/telegram-draft";
import type { TelegramBot, TelegramChat, TelegramPreset } from "@/features/configuration/types";

type PresetAction = (action:
  | { action: "preset.save"; data: { id?: string; name: string; bot_id: string; group_ids: string[]; channel_ids: string[] } }
  | { action: "preset.remove"; data: { id: string } },
) => Promise<unknown>;

function TelegramPresetPanel({
  presets,
  bots,
  groups,
  channels,
  busy,
  onAction,
  onDirtyChange,
}: {
  presets: TelegramPreset[];
  bots: TelegramBot[];
  groups: TelegramChat[];
  channels: TelegramChat[];
  busy: boolean;
  onAction: PresetAction;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const confirmation = useConfirmationDialog();
  const [editing, setEditing] = useState<TelegramPreset | null>(null);
  const [name, setName] = useState("");
  const [botId, setBotId] = useState("");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [channelIds, setChannelIds] = useState<string[]>([]);
  const dirty = telegramPresetDraftIsDirty(editing, { name, botId, groupIds, channelIds });

  useEffect(() => {
    setName(editing?.name || "");
    setBotId(editing?.bot_ids?.[0] || "");
    setGroupIds(editing?.group_ids || []);
    setChannelIds(editing?.channel_ids || []);
  }, [editing]);

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  function toggle(ids: string[], id: string, update: (next: string[]) => void) {
    update(ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id]);
  }

  async function discardDraft(description: string) {
    if (!dirty) return true;
    return confirmation.confirm({ title: "Modifiche non salvate", description, confirmLabel: "Scarta modifiche", tone: "danger" });
  }

  async function openEditor(next: TelegramPreset) {
    if (!await discardDraft("Aprire un'altra preconfigurazione e perdere le modifiche in corso?")) return;
    setEditing(next);
  }

  async function cancelEditor() {
    if (!await discardDraft("Annullare e perdere le modifiche in corso?")) return;
    setEditing(null);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onAction({ action: "preset.save", data: { id: editing?.id, name, bot_id: botId, group_ids: groupIds, channel_ids: channelIds } })
      .then(() => setEditing(null))
      .catch(() => undefined);
  }

  function nameFor(id: string, entries: Array<TelegramBot | TelegramChat>) {
    const entry = entries.find((item) => item.id === id);
    if (!entry) return id;
    return "chat_id" in entry
      ? entry.alias || entry.original_name || entry.chat_id
      : entry.alias || entry.original_name || entry.username || "Bot";
  }

  async function removePreset(preset: TelegramPreset) {
    if (!await confirmation.confirm({ title: "Rimuovi preconfigurazione", description: `Rimuovere la preconfigurazione ${preset.name}?`, confirmLabel: "Rimuovi preset", tone: "danger" })) return;
    void onAction({ action: "preset.remove", data: { id: preset.id } }).catch(() => undefined);
  }

  return <section className="telegram-preset-panel">
    <header>
      <div><h3 className="contextual-heading" title="Destinazioni">Preconfigurazioni</h3><p>Combina un bot con gruppi e canali pronti per le notifiche.</p></div>
      <Button type="button" requiresWriteAccess variant="primary" size="compact" onClick={() => void openEditor({} as TelegramPreset)} disabled={busy || !bots.length}><Plus size={15} aria-hidden="true" />Crea preset</Button>
    </header>
    {!bots.length ? <div className="inline-alert inline-alert--error" role="status">Salva almeno un bot prima di creare una preconfigurazione.</div> : null}
    {editing ? <form className="telegram-preset-form" onSubmit={submit} aria-busy={busy}>
      <label>Nome preconfigurazione<input type="text" required disabled={busy} placeholder="Notifiche Emby Green" value={name} onChange={(event) => setName(event.target.value)} /></label>
      <fieldset disabled={busy}><legend>Bot</legend>{bots.map((bot) => <label key={bot.id} className="configuration-check"><input type="radio" name="telegram-preset-bot" value={bot.id} checked={bot.id === botId} onChange={() => setBotId(bot.id)} />{bot.alias || bot.original_name || bot.username || "Bot Telegram"}</label>)}</fieldset>
      <fieldset disabled={busy}><legend>Canali</legend>{channels.length ? channels.map((channel) => <label key={channel.id} className="configuration-check"><input type="checkbox" checked={channelIds.includes(channel.id)} onChange={() => toggle(channelIds, channel.id, setChannelIds)} />{channel.alias || channel.original_name || channel.chat_id}</label>) : <span>Nessun canale disponibile.</span>}</fieldset>
      <fieldset disabled={busy}><legend>Gruppi</legend>{groups.length ? groups.map((group) => <label key={group.id} className="configuration-check"><input type="checkbox" checked={groupIds.includes(group.id)} onChange={() => toggle(groupIds, group.id, setGroupIds)} />{group.alias || group.original_name || group.chat_id}</label>) : <span>Nessun gruppo disponibile.</span>}</fieldset>
      <footer><Button type="button" variant="ghost" size="compact" onClick={() => void cancelEditor()} disabled={busy}>Annulla</Button><Button type="submit" variant="primary" size="compact" disabled={busy || !botId || (!groupIds.length && !channelIds.length)}>{editing.id ? "Aggiorna preset" : "Salva preset"}</Button></footer>
    </form> : null}
    <div className="telegram-preset-list">
      {presets.length ? presets.map((preset) => <article key={preset.id} className="telegram-preset-card">
        <div>
          <strong>{preset.name}</strong>
          <dl>
            <div><dt>Bot</dt><dd>{preset.bot_ids.map((id) => nameFor(id, bots)).join(", ") || "-"}</dd></div>
            <div><dt>Canali</dt><dd><TelegramPresetDestinationStatus ids={preset.channel_ids} entries={channels} kind="channels" alerts={preset.alerts} /></dd></div>
            <div><dt>Gruppi</dt><dd><TelegramPresetDestinationStatus ids={preset.group_ids} entries={groups} kind="groups" alerts={preset.alerts} /></dd></div>
          </dl>
        </div>
        <div className="telegram-resource-actions">
          <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Modifica preset" aria-label="Modifica preset" onClick={() => void openEditor(preset)} disabled={busy}><Pencil size={15} aria-hidden="true" /></Button>
          <Button type="button" requiresWriteAccess variant="ghost" size="icon" className="danger-action" title="Rimuovi preset" aria-label="Rimuovi preset" onClick={() => void removePreset(preset)} disabled={busy}><Trash2 size={15} aria-hidden="true" /></Button>
        </div>
      </article>) : <p className="telegram-empty">Nessuna preconfigurazione configurata.</p>}
    </div>
    {confirmation.dialog}
  </section>;
}

export { TelegramPresetPanel };
