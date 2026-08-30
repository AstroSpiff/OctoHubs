import { KeyRound, Save, Trash2 } from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  embyServerInputFromSettings,
  refreshedEmbyServerDraft,
  sameEmbyServerInput,
} from "@/features/configuration/emby-server-draft";
import { EmbyServerIconPicker } from "@/features/configuration/components/emby-server-icon-picker";
import type { EmbyServerInput, EmbyServerSettings } from "@/features/configuration/types";

function EmbyServerEditor({ server, saving, deleting, onSave, onDelete, onCancel, editorId, onDirtyChange }: { server?: EmbyServerSettings; saving: boolean; deleting: boolean; onSave: (input: EmbyServerInput) => Promise<void>; onDelete?: () => void; onCancel?: () => void; editorId?: string; onDirtyChange?: (editorId: string, dirty: boolean) => void }) {
  const [draft, setDraft] = useState<EmbyServerInput>(() => embyServerInputFromSettings(server));
  const baseline = useRef(embyServerInputFromSettings(server));
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [error, setError] = useState("");
  const busy = saving || deleting;
  const dirty = !sameEmbyServerInput(draft, baseline.current) || Boolean(apiKey) || clearApiKey;

  useEffect(() => {
    const next = embyServerInputFromSettings(server);
    const previous = baseline.current;
    baseline.current = next;
    setDraft((current) => refreshedEmbyServerDraft(current, previous, next));
  }, [server]);

  useEffect(() => {
    if (!editorId) return;
    onDirtyChange?.(editorId, dirty);
    return () => onDirtyChange?.(editorId, false);
  }, [dirty, editorId, onDirtyChange]);

  function update<Key extends keyof EmbyServerInput>(key: Key, value: EmbyServerInput[Key]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      await onSave({ ...draft, ...(apiKey ? { api_key: apiKey } : {}), ...(clearApiKey ? { clear_api_key: true } : {}) });
      setApiKey("");
      setClearApiKey(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossibile salvare il server Emby.");
    }
  }

  function remove() {
    onDelete?.();
  }

  function resetDraft() {
    setDraft({ ...baseline.current });
    setApiKey("");
    setClearApiKey(false);
    setError("");
  }

  return <form className="configuration-server-editor" onSubmit={submit}>
    <div className="configuration-server-editor-heading">
      <div><h3>{server?.name || "Nuovo server Emby"}</h3>{server?.original_name && server.original_name !== server.name ? <p>{server.original_name}</p> : null}</div>
      {server ? <label className="configuration-switch"><input type="checkbox" checked={draft.enabled} disabled={busy} onChange={(event) => update("enabled", event.target.checked)} /><span>Abilitato</span></label> : null}
    </div>
    {error ? <p className="configuration-form-error" role="alert">{error}</p> : null}
    {dirty ? <div className="configuration-draft-state" role="status"><span>Modifiche non salvate</span><Button type="button" variant="ghost" size="compact" onClick={resetDraft} disabled={busy}>Ripristina valori salvati</Button></div> : null}
    <div className="configuration-server-fields">
      <EmbyServerIconPicker icon={draft.icon} color={draft.icon_color} disabled={busy} onIconChange={(value) => update("icon", value)} onColorChange={(value) => update("icon_color", value)} />
      <label><span>Alias</span><input value={draft.alias} disabled={busy} onChange={(event) => update("alias", event.target.value)} placeholder="Nome mostrato in OctoHubs" /></label>
      <label><span>URL Emby</span><input type="url" value={draft.url} required disabled={busy} onChange={(event) => update("url", event.target.value)} placeholder="http://emby:8096" /></label>
      <label><span>API key</span><div className="configuration-secret-input"><KeyRound size={15} aria-hidden="true" /><input type="password" value={apiKey} disabled={busy || clearApiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={server?.api_key_configured ? "Già configurata" : "Inserisci API key"} autoComplete="new-password" /></div></label>
      {server?.api_key_configured ? <label className="configuration-checkbox"><input type="checkbox" checked={clearApiKey} disabled={busy} onChange={(event) => setClearApiKey(event.target.checked)} />Rimuovi la key salvata</label> : null}
    </div>
    <details className="configuration-advanced"><summary>Opzioni avanzate</summary><label><span>Note</span><textarea value={draft.notes} disabled={busy} onChange={(event) => update("notes", event.target.value)} placeholder="Note interne sul server" rows={2} /></label></details>
    <footer>{onCancel ? <Button type="button" variant="ghost" size="compact" onClick={onCancel} disabled={busy}>Annulla</Button> : null}<Button type="submit" variant="primary" size="compact" disabled={busy}><Save size={16} aria-hidden="true" />{saving ? "Salvataggio..." : "Salva server"}</Button>{server ? <Button type="button" variant="danger" size="compact" onClick={remove} disabled={busy}><Trash2 size={16} aria-hidden="true" />{deleting ? "Rimozione..." : "Rimuovi"}</Button> : null}</footer>
  </form>;
}

export { EmbyServerEditor };
