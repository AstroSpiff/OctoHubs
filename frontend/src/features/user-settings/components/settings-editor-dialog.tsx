import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceChoiceGroup } from "@/components/ui/workspace-choice-group";
import { useDirtyChange } from "@/lib/use-dirty-change";
import {
  getSettingsInfo,
  getSettingsSchema,
  saveSettings,
} from "@/features/user-settings/api";
import { SettingsEditorStatus } from "@/features/user-settings/components/settings-editor-status";
import { SettingsPresetControls } from "@/features/user-settings/components/settings-preset-controls";
import { SettingsScopePanel } from "@/features/user-settings/components/settings-scope-panel";
import {
  mergeUserSettings,
  normalizeUserSettings,
  userSettingsMatch,
} from "@/features/user-settings/settings-model";
import type {
  LibrarySettingItem,
  SettingsFeatureItem,
  SettingsInfo,
  SettingsSchema,
  SettingsScope,
  SettingsTarget,
  UserSettings,
} from "@/features/user-settings/types";

const tabs: Array<{
  id: SettingsScope;
  label: string;
  description: string;
}> = [
  {
    id: "policy",
    label: "Permessi",
    description: "Accesso, riproduzione, limiti e librerie.",
  },
  {
    id: "config",
    label: "Configurazione",
    description: "Preferenze utente e comportamento di Emby.",
  },
  {
    id: "display_preferences",
    label: "Interfaccia",
    description: "Preferenze del client e della visualizzazione.",
  },
];

type SettingsEditorDialogProps = {
  target: SettingsTarget | null;
  onClose: () => void;
  onSaved: () => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function SettingsEditorDialog({
  target,
  onClose,
  onSaved,
  onDirtyChange,
}: SettingsEditorDialogProps) {
  const confirmation = useConfirmationDialog();
  const [schema, setSchema] = useState<SettingsSchema | null>(null);
  const [settings, setSettings] = useState<UserSettings>(() =>
    normalizeUserSettings(undefined),
  );
  const [savedSettings, setSavedSettings] = useState<UserSettings>(() =>
    normalizeUserSettings(undefined),
  );
  const [libraryItems, setLibraryItems] = useState<LibrarySettingItem[]>([]);
  const [featureItems, setFeatureItems] = useState<SettingsFeatureItem[]>([]);
  const [settingsInfo, setSettingsInfo] = useState<SettingsInfo | null>(null);
  const [activeTab, setActiveTab] = useState<SettingsScope>("policy");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!target) return;
    let active = true;
    setLoading(true);
    setError("");
    setSaved(false);
    setActiveTab("policy");
    setFeatureItems([]);
    setSettingsInfo(null);
    Promise.all([getSettingsSchema(), getSettingsInfo(target)])
      .then(([nextSchema, info]) => {
        if (!active) return;
        const nextSettings = normalizeUserSettings(info.settings);
        setSchema(nextSchema);
        setSettings(nextSettings);
        setSavedSettings(nextSettings);
        setLibraryItems(info.library_items || []);
        setFeatureItems(info.feature_items || []);
        setSettingsInfo(info);
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
  }, [target]);

  const dirty = !loading && !userSettingsMatch(settings, savedSettings);
  useDirtyChange(Boolean(target), dirty, onDirtyChange);

  if (!target) return null;

  const activeTarget = target;
  const statusTarget =
    saved && activeTarget.scope === "group"
      ? { ...activeTarget, mismatchCount: 0 }
      : activeTarget;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await saveSettings({ target: activeTarget, settings });
      setSavedSettings(settings);
      setSaved(true);
      try {
        const refreshedInfo = await getSettingsInfo(activeTarget);
        setSettings(normalizeUserSettings(refreshedInfo.settings));
        setSavedSettings(normalizeUserSettings(refreshedInfo.settings));
        setLibraryItems(refreshedInfo.library_items || []);
        setFeatureItems(refreshedInfo.feature_items || []);
        setSettingsInfo(refreshedInfo);
      } catch {
        setSettingsInfo((current) => current ? { ...current, saved: true } : current);
      }
      onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Errore salvataggio impostazioni",
      );
    } finally {
      setSaving(false);
    }
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
        "Chiudere l'editor e perdere le modifiche alle impostazioni Emby?",
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
          className="user-settings-dialog"
          onSubmit={submit}
          role="dialog"
          aria-modal="true"
          aria-labelledby="settings-editor-title"
        >
          <header>
            <div>
              <h2 id="settings-editor-title" className="contextual-heading" title="Impostazioni Emby">{activeTarget.name}</h2>
              <p>
                Le modifiche vengono applicate a{" "}
                {activeTarget.scope === "group"
                  ? "tutti gli utenti del gruppo"
                  : "questo utente"}
                .
              </p>
            </div>
          </header>
          <SettingsEditorStatus target={statusTarget} info={settingsInfo} />

          {error ? (
            <p className="users-dialog-error" role="alert">
              {error}
            </p>
          ) : null}
          {saved ? (
            <p className="user-settings-saved" role="status">
              Impostazioni salvate e applicate.
            </p>
          ) : null}
          {loading ? (
            <p className="user-settings-loading">
              Caricamento impostazioni...
            </p>
          ) : null}
          {schema ? (
            <SettingsEditorForm
              schema={schema}
              settings={settings}
              libraryItems={libraryItems}
              featureItems={featureItems}
              activeTab={activeTab}
              saving={saving}
              onBeforePresetLoad={async () => {
                if (!dirty) return true;
                return confirmation.confirm({
                  title: "Modifiche non salvate",
                  description:
                    "Caricare il preset sostituira' le modifiche correnti alle impostazioni Emby.",
                  confirmLabel: "Carica preset",
                  tone: "danger",
                });
              }}
              onActiveTabChange={setActiveTab}
              onSettingsChange={(nextSettings) => {
                setSettings(nextSettings);
                setSaved(false);
              }}
            />
          ) : null}

          <footer>
            <Button
              type="button"
              variant="ghost"
              onClick={() => void requestClose()}
              disabled={saving}
            >
              Chiudi
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={loading || !schema || saving}
            >
              {saving ? "Salvataggio..." : "Salva impostazioni"}
            </Button>
          </footer>
        </form>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

function SettingsEditorForm({
  schema,
  settings,
  libraryItems,
  featureItems,
  activeTab,
  saving,
  onBeforePresetLoad,
  onActiveTabChange,
  onSettingsChange,
}: {
  schema: SettingsSchema;
  settings: UserSettings;
  libraryItems: LibrarySettingItem[];
  featureItems: SettingsFeatureItem[];
  activeTab: SettingsScope;
  saving: boolean;
  onBeforePresetLoad: () => Promise<boolean>;
  onActiveTabChange: (scope: SettingsScope) => void;
  onSettingsChange: (settings: UserSettings) => void;
}) {
  const activeTabDetails = tabs.find((tab) => tab.id === activeTab);

  return (
    <>
      <SettingsPresetControls
        settings={settings}
        applyLibraries
        disabled={saving}
        onBeforeLoad={onBeforePresetLoad}
        onLoad={(preset) =>
          onSettingsChange(
            mergeUserSettings(
              settings,
              preset.settings,
              preset.apply_libraries === true,
            ),
          )
        }
      />
      <WorkspaceChoiceGroup
        className="user-settings-tabs"
        ariaLabel="Sezioni impostazioni"
        idPrefix="user-settings-tab"
        mode="tab"
        value={activeTab}
        options={tabs.map((tab) => ({
          id: tab.id,
          content: tab.label,
          controls: `user-settings-panel-${tab.id}`,
        }))}
        onChange={(scope) => onActiveTabChange(scope as SettingsScope)}
      />
      <p className="user-settings-tab-note">{activeTabDetails?.description}</p>
      <div
        id={`user-settings-panel-${activeTab}`}
        className="user-settings-panel"
        role="tabpanel"
        aria-labelledby={`user-settings-tab-${activeTab}`}
        tabIndex={0}
      >
        <SettingsScopePanel
          scope={activeTab}
          categories={schema.categories}
          settings={settings}
          libraryItems={libraryItems}
          featureItems={featureItems}
          disabled={saving}
          onChange={onSettingsChange}
        />
      </div>
    </>
  );
}

export { SettingsEditorDialog };
