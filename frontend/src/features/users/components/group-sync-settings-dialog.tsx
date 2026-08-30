import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { useDirtyChange } from "@/lib/use-dirty-change";
import { useSynchronizedDraft } from "@/lib/use-synchronized-draft";
import { groupSyncSettingsFrom } from "@/features/users/group-sync-settings-state";
import { userConfigurationCategories } from "@/features/users/user-configuration-categories";
import type { EmbyUserGroup, GroupSyncSettings } from "@/features/users/types";

type GroupSyncSettingsDialogProps = {
  group: EmbyUserGroup | null;
  saving: boolean;
  syncing?: boolean;
  error?: string;
  onClose: () => void;
  onSave: (settings: GroupSyncSettings) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function GroupSyncSettingsDialog({ group, saving, syncing = false, error, onClose, onSave, onDirtyChange }: GroupSyncSettingsDialogProps) {
  const confirmation = useConfirmationDialog();
  const { dirty, draft: settings, setDraft: setSettings } = useSynchronizedDraft(
    group || undefined,
    groupSyncSettingsFrom,
  );
  useDirtyChange(Boolean(group && settings), dirty, onDirtyChange);

  if (!group || !settings) return null;

  const currentSettings = settings;
  const controlsDisabled = !currentSettings.auto_sync || saving || syncing;
  const resumeDisabled = controlsDisabled || !currentSettings.sync_playstate;

  function updateSetting<Key extends keyof GroupSyncSettings>(key: Key, value: GroupSyncSettings[Key]) {
    setSettings((current) => current ? { ...current, [key]: value } : current);
  }

  function toggleCategory(category: string) {
    const selected = new Set(currentSettings.config_categories || []);
    if (selected.has(category)) selected.delete(category);
    else selected.add(category);
    updateSetting("config_categories", [...selected]);
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSave({ ...currentSettings, sync_resume: currentSettings.sync_playstate ? currentSettings.sync_resume : false });
  }

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Modifiche non salvate",
      description:
        "Chiudere la configurazione del gruppo e perdere le modifiche?",
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
        <form className="users-sync-dialog" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="group-sync-settings-title">
        <header>
          <div>
            <h2 id="group-sync-settings-title" className="contextual-heading" title="Sincronizzazione gruppo">{group.name}</h2>
          </div>
        </header>

        {error ? <p className="users-dialog-error" role="alert">Salvataggio impostazioni gruppo non riuscito: {error}</p> : null}
        {syncing ? <p className="users-sync-note" role="status">Sincronizzazione in corso. Le impostazioni torneranno modificabili al termine.</p> : null}

        <label className="users-sync-primary-toggle">
          <input type="checkbox" checked={settings.auto_sync === true} onChange={(event) => updateSetting("auto_sync", event.target.checked)} disabled={saving || syncing} />
          <span>
            <strong>Sincronizzazione automatica</strong>
            <small>Applica le opzioni scelte quando il servizio di sincronizzazione rileva cambiamenti.</small>
          </span>
        </label>

        <fieldset disabled={controlsDisabled}>
          <legend>Modalità</legend>
          <label className="users-sync-field">
            <span>Direzione</span>
            <select value={settings.sync_type || "merge"} onChange={(event) => updateSetting("sync_type", event.target.value as "merge" | "one_way")}>
              <option value="merge">Bidirezionale: unisce e applica l&apos;ultima modifica</option>
              <option value="one_way">Unidirezionale: dal leader agli altri utenti</option>
            </select>
          </label>
        </fieldset>

        <fieldset disabled={controlsDisabled}>
          <legend>Dati da sincronizzare</legend>
          <div className="users-sync-option-grid">
            <SyncToggle label="Visti" hint="Mantiene lo stato visto tra gli utenti del gruppo." checked={settings.sync_playstate !== false} onChange={(value) => updateSetting("sync_playstate", value)} />
            <SyncToggle label="Riprendi" hint="Include la posizione di ripresa." checked={settings.sync_resume === true} disabled={resumeDisabled} onChange={(value) => updateSetting("sync_resume", value)} />
            <SyncToggle label="Impostazioni Emby" hint="Copia solo le categorie sicure selezionate sotto." checked={settings.sync_config === true} onChange={(value) => updateSetting("sync_config", value)} />
            <SyncToggle label="Accesso librerie" hint="Usa le associazioni librerie configurate nello scan." checked={settings.sync_library_access === true} onChange={(value) => updateSetting("sync_library_access", value)} />
            <SyncToggle label="Preferiti" hint="Alla prima sincronizzazione unisce le raccolte, poi applica le differenze." checked={settings.sync_favorites === true} onChange={(value) => updateSetting("sync_favorites", value)} />
            <SyncToggle label="Playlist" hint="Alla prima sincronizzazione unisce le playlist, poi applica le differenze." checked={settings.sync_playlists === true} onChange={(value) => updateSetting("sync_playlists", value)} />
          </div>
        </fieldset>

        <fieldset disabled={controlsDisabled || !settings.sync_config}>
          <legend>Categorie impostazioni</legend>
          <p className="users-sync-help">Sono usate solo quando “Impostazioni Emby” è attivo.</p>
          <div className="users-sync-category-grid">
            {userConfigurationCategories.map((category) => (
              <label key={category.id} className="users-sync-check">
                <input type="checkbox" checked={settings.config_categories?.includes(category.id) || false} onChange={() => toggleCategory(category.id)} />
                {category.label}
              </label>
            ))}
          </div>
        </fieldset>

        <p className="users-sync-note">Visti, preferiti e playlist uniscono i dati alla prima sincronizzazione; dalle successive viene applicata la modalità scelta.</p>

        <footer>
          <Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={saving}>Annulla</Button>
          <Button type="submit" variant="primary" disabled={saving || syncing}>{saving ? "Salvataggio..." : syncing ? "Sincronizzazione in corso..." : "Salva impostazioni"}</Button>
        </footer>
        </form>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

function SyncToggle({ label, hint, checked, disabled = false, onChange }: { label: string; hint: string; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="users-sync-toggle">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span><strong>{label}</strong><small>{hint}</small></span>
    </label>
  );
}

export { GroupSyncSettingsDialog };
