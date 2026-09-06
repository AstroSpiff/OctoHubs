import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceChoiceGroup } from "@/components/ui/workspace-choice-group";
import { useDirtyChange } from "@/lib/use-dirty-change";
import { getSettingsInfo, getSettingsSchema } from "@/features/user-settings/api";
import { SettingsFieldControl } from "@/features/user-settings/components/settings-field";
import { SettingsLibraryAccess } from "@/features/user-settings/components/settings-library-access";
import { SettingsPresetControls } from "@/features/user-settings/components/settings-preset-controls";
import { BulkSettingsOverview } from "@/features/users/components/bulk-settings-overview";
import { groupSettingsFields } from "@/features/user-settings/settings-field-groups";
import { prepareSettingsCategories } from "@/features/user-settings/settings-schema-preparation";
import { normalizeUserSettings, updateSettingsValue } from "@/features/user-settings/settings-model";
import type { LibrarySettingItem, SettingsFeatureItem, SettingsField, SettingsSchema, SettingsScope, UserSettings } from "@/features/user-settings/types";
import type { EmbyUser } from "@/features/users/types";

const tabs: Array<{ id: SettingsScope; label: string }> = [
  { id: "policy", label: "Permessi" },
  { id: "config", label: "Configurazione" },
  { id: "display_preferences", label: "Interfaccia" },
];

const blockedFields: Record<SettingsScope, Set<string>> = {
  policy: new Set(["IsAdministrator", "IsDisabled", "Authentication", "AuthenticationProviderId", "Password", "InvalidLoginAttemptCount", "LoginAttemptsBeforeLockout", "EnableAllFolders", "EnabledFolders", "EnabledLibraryFolders", "EnabledMediaFolders", "ExcludedSubFolders", "BlockedTags", "BlockedMediaTags", "AccessSchedules", "MaxActiveSessions", "SyncPlayfield"]),
  config: new Set(["MyMediaExcludes", "GroupedFolders", "DashboardLayout", "HomePageSectionOrder", "LandingScreen", "LatestItemsExcludes"]),
  display_preferences: new Set(),
};

type BulkSettingsDialogProps = {
  users: EmbyUser[];
  saving: boolean;
  mutationError?: string;
  onClose: () => void;
  onApply: (input: { users: EmbyUser[]; settings: UserSettings; applyLibraries: boolean }) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function BulkSettingsDialog({ users, saving, mutationError, onClose, onApply, onDirtyChange }: BulkSettingsDialogProps) {
  const confirmation = useConfirmationDialog();
  const [schema, setSchema] = useState<SettingsSchema | null>(null);
  const [libraryItems, setLibraryItems] = useState<LibrarySettingItem[]>([]);
  const [featureItems, setFeatureItems] = useState<SettingsFeatureItem[]>([]);
  const [settings, setSettings] = useState<UserSettings>(() => normalizeUserSettings(undefined));
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set());
  const [applyLibraries, setApplyLibraries] = useState(false);
  const [activeTab, setActiveTab] = useState<SettingsScope>("policy");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loadedUsersIdentity, setLoadedUsersIdentity] = useState("");
  const usersIdentity = users.map((user) => `${user.server_id}:${user.user_id}`).join("|");

  useEffect(() => {
    if (!users.length) return;
    let active = true;
    setLoading(true);
    setSchema(null);
    setLoadedUsersIdentity("");
    setSettings(normalizeUserSettings(undefined));
    setSelectedFields(new Set());
    setApplyLibraries(false);
    setLibraryItems([]);
    setFeatureItems([]);
    setActiveTab("policy");
    setError("");
    Promise.all([getSettingsSchema(), getSettingsInfo({ scope: "user", serverId: users[0].server_id, userId: users[0].user_id, name: users[0].name })])
      .then(([nextSchema, info]) => {
        if (!active) return;
        setSchema(nextSchema);
        setLibraryItems(info.library_items || []);
        setFeatureItems(info.feature_items || []);
        setLoadedUsersIdentity(usersIdentity);
      })
      .catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [users, usersIdentity]);

  const authoritative = Boolean(schema && loadedUsersIdentity === usersIdentity);

  const appliedCount = selectedFields.size + (applyLibraries ? 1 : 0);
  const activeSections = useMemo(() => prepareSettingsCategories(schema?.categories || [], featureItems).map((category) => ({
    category,
    fields: (category[activeTab] || []).filter((field) => !field.hidden && field.type !== "library_landing" && !blockedFields[activeTab].has(field.key)),
  })).filter(({ category, fields }) => fields.length || (activeTab === "policy" && category.libraries)), [activeTab, featureItems, schema]);

  const dirty = authoritative && (selectedFields.size > 0 || applyLibraries);
  useDirtyChange(users.length > 0, dirty, onDirtyChange);

  if (!users.length) return null;

  function fieldKey(scope: SettingsScope, field: SettingsField) {
    return `${scope}:${field.key}`;
  }

  function toggleField(scope: SettingsScope, field: SettingsField, checked: boolean) {
    const key = fieldKey(scope, field);
    setSelectedFields((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authoritative) return;
    if (!appliedCount) return setError("Seleziona almeno un campo o l'accesso alle librerie.");
    const patch = buildSettingsPatch(settings, selectedFields, applyLibraries);
    setError("");
    onApply({ users, settings: patch, applyLibraries });
  }

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Modifiche non applicate",
      description:
        "Chiudere l'editor e perdere le impostazioni selezionate per gli utenti?",
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
        <form className="user-settings-dialog user-settings-dialog--bulk" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="bulk-settings-title">
        <header>
          <h2 id="bulk-settings-title" className="contextual-heading" title="Applicazione selettiva">Impostazioni per {users.length} utenti</h2>
          <p>Vengono modificati solo i campi marcati. Le impostazioni amministrative, password e protezioni non sono disponibili in questa azione.</p>
        </header>
        <BulkSettingsOverview
          users={users}
          selectedFieldCount={selectedFields.size}
          applyLibraries={applyLibraries}
        />
        {error || mutationError ? <p className="users-dialog-error" role="alert">{error || mutationError}</p> : null}
        {loading || (!authoritative && !error) ? <p className="user-settings-loading">Caricamento schema impostazioni...</p> : null}
        {schema && authoritative ? <>
          <SettingsPresetControls
            settings={buildSettingsPatch(settings, selectedFields, applyLibraries)}
            applyLibraries={applyLibraries}
            disabled={saving}
            onBeforeLoad={async () => {
              if (!dirty) return true;
              return confirmation.confirm({
                title: "Modifiche non applicate",
                description:
                  "Caricare il preset sostituira' i campi gia' selezionati per gli utenti.",
                confirmLabel: "Carica preset",
                tone: "danger",
              });
            }}
            onLoad={(preset) => {
              const nextSettings = normalizeUserSettings(preset.settings);
              const nextSelected = new Set<string>();
              for (const scope of tabs.map((tab) => tab.id)) {
                for (const key of Object.keys(preset.settings[scope] || {})) {
                  if (!blockedFields[scope].has(key)) {
                    nextSelected.add(`${scope}:${key}`);
                  }
                }
              }
              setSettings(nextSettings);
              setSelectedFields(nextSelected);
              setApplyLibraries(preset.apply_libraries === true);
              setError("");
            }}
          />
          <WorkspaceChoiceGroup
            className="user-settings-tabs"
            ariaLabel="Sezioni impostazioni massive"
            idPrefix="bulk-settings-tab"
            mode="tab"
            value={activeTab}
            options={tabs.map((tab) => ({
              id: tab.id,
              content: tab.label,
              controls: `bulk-settings-panel-${tab.id}`,
            }))}
            onChange={(scope) => setActiveTab(scope as SettingsScope)}
          />
          <p className="user-settings-tab-note">{appliedCount === 1 ? "1 modifica selezionata." : `${appliedCount} modifiche selezionate.`}</p>
          <div
            id={`bulk-settings-panel-${activeTab}`}
            className="user-settings-panel"
            role="tabpanel"
            aria-labelledby={`bulk-settings-tab-${activeTab}`}
            tabIndex={0}
          >
            <div className="bulk-settings-sections">
              {activeSections.map(({ category, fields }, index) => <details key={category.id} className="user-settings-section" open={index === 0}>
                <summary><span>{category.label || category.id}</span><small>{fields.length ? `${fields.length} campi` : "Librerie"}</small></summary>
                <div>
                  {category.description ? <p>{category.description}</p> : null}
                  {activeTab === "policy" && category.libraries ? <section className="bulk-settings-library"><label className="bulk-settings-field-toggle"><input type="checkbox" checked={applyLibraries} disabled={saving} onChange={(event) => setApplyLibraries(event.target.checked)} /><span>Applica accesso librerie</span></label><SettingsLibraryAccess settings={settings} items={libraryItems} disabled={saving || !applyLibraries} onChange={(libraries) => setSettings((current) => ({ ...current, libraries }))} /></section> : null}
                  {groupSettingsFields(fields).map((fieldGroup, groupIndex) => <section key={`${fieldGroup.label || "fields"}:${groupIndex}`} className="bulk-settings-field-group">{fieldGroup.label ? <h4>{fieldGroup.label}</h4> : null}{fieldGroup.fields.map((field) => <BulkSettingsField key={fieldKey(activeTab, field)} field={field} scope={activeTab} value={settings[activeTab][field.key]} selected={selectedFields.has(fieldKey(activeTab, field))} disabled={saving} libraryItems={libraryItems} onSelected={(checked) => toggleField(activeTab, field, checked)} onChange={(value) => setSettings((current) => updateSettingsValue(current, activeTab, field.key, value))} />)}</section>)}
                </div>
              </details>)}
            </div>
          </div>
        </> : null}
        <footer>
          <Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={saving}>Annulla</Button>
          <Button type="submit" variant="primary" disabled={!authoritative || !appliedCount || saving}>{saving ? "Applicazione..." : "Applica impostazioni"}</Button>
        </footer>
        </form>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

function BulkSettingsField({ field, scope, value, selected, disabled, libraryItems, onSelected, onChange }: { field: SettingsField; scope: SettingsScope; value: unknown; selected: boolean; disabled: boolean; libraryItems: LibrarySettingItem[]; onSelected: (checked: boolean) => void; onChange: (value: unknown) => void }) {
  return <section className={`bulk-settings-field ${selected ? "is-selected" : ""}`}><label className="bulk-settings-field-toggle"><input type="checkbox" checked={selected} disabled={disabled} onChange={(event) => onSelected(event.target.checked)} /><span>Applica questo campo</span></label><SettingsFieldControl field={field} scope={scope} value={value} disabled={disabled || !selected} libraryItems={libraryItems} onChange={onChange} /></section>;
}

function buildSettingsPatch(settings: UserSettings, selectedFields: Set<string>, applyLibraries: boolean): UserSettings {
  const patch = normalizeUserSettings(undefined);
  for (const scope of tabs.map((tab) => tab.id)) {
    for (const [key, value] of Object.entries(settings[scope])) {
      if (selectedFields.has(`${scope}:${key}`)) patch[scope][key] = value;
    }
  }
  if (applyLibraries) patch.libraries = settings.libraries;
  return patch;
}

export { BulkSettingsDialog };
