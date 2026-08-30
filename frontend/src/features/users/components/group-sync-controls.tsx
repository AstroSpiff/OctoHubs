import { RefreshCw } from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { usePopoverDisclosure } from "@/components/ui/use-popover-disclosure";
import { GroupSyncStatus } from "@/features/users/components/group-sync-status";
import {
  groupSyncSettingsFrom,
  groupSyncSettingsMatch,
} from "@/features/users/group-sync-settings-state";
import { userConfigurationCategories } from "@/features/users/user-configuration-categories";
import type { EmbyUserGroup, GroupSyncSettings } from "@/features/users/types";

const syncOptions = [
  ["sync_playstate", "Visti"],
  ["sync_resume", "Riprendi"],
  ["sync_config", "Impostazioni Emby"],
  ["sync_library_access", "Accesso librerie"],
  ["sync_favorites", "Preferiti"],
  ["sync_playlists", "Playlist"],
] as const;

type GroupSyncControlsProps = {
  group: EmbyUserGroup;
  saving: boolean;
  syncing: boolean;
  onSave: (settings: GroupSyncSettings) => Promise<void>;
  onSync: () => void;
};

function GroupSyncControls({ group, saving, syncing, onSave, onSync }: GroupSyncControlsProps) {
  const [settings, setSettings] = useState(() => groupSyncSettingsFrom(group));
  const [persisting, setPersisting] = useState(false);
  const settingsRef = useRef(settings);
  const persistingRef = useRef(false);
  const syncOptionsPopover = usePopoverDisclosure();

  useEffect(() => {
    if (persistingRef.current) return;
    const incoming = groupSyncSettingsFrom(group);
    if (groupSyncSettingsMatch(settingsRef.current, incoming)) return;
    settingsRef.current = incoming;
    setSettings(incoming);
  }, [group]);

  if (!group.is_linked || group.is_owners) return null;

  async function update(next: GroupSyncSettings) {
    if (persistingRef.current) return;
    const normalized = {
      ...next,
      sync_resume: next.sync_playstate ? next.sync_resume : false,
    };
    persistingRef.current = true;
    setSettings(normalized);
    settingsRef.current = normalized;
    setPersisting(true);
    try {
      await onSave(normalized);
    } finally {
      persistingRef.current = false;
      setPersisting(false);
    }
  }

  function setField<Key extends keyof GroupSyncSettings>(key: Key, value: GroupSyncSettings[Key]) {
    void update({ ...settingsRef.current, [key]: value });
  }

  function toggleCategory(category: string) {
    const selected = new Set(settings.config_categories || []);
    if (selected.has(category)) selected.delete(category);
    else selected.add(category);
    setField("config_categories", [...selected]);
  }

  const busy = saving || syncing || persisting;
  const disabled = !settings.auto_sync || busy;

  return (
    <div className="users-group-sync-area">
      <label className="users-group-sync-toggle" title="Attiva o disattiva la sincronizzazione automatica per questo gruppo.">
        <input
          type="checkbox"
          checked={settings.auto_sync === true}
          disabled={busy}
          onChange={(event) => setField("auto_sync", event.target.checked)}
        />
        <span>Auto Sync</span>
      </label>

      {settings.auto_sync ? (
        <div className="users-group-sync-controls">
          <label className="users-group-sync-mode">
            <span>Direzione</span>
            <select
              value={settings.sync_type || "merge"}
              disabled={disabled}
              onChange={(event) => setField("sync_type", event.target.value as "merge" | "one_way")}
            >
              <option value="merge">Bidirezionale</option>
              <option value="one_way">Monodirezionale</option>
            </select>
          </label>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Sincronizza ora con le impostazioni del gruppo"
            aria-label={`Sincronizza ora ${group.name}`}
            onClick={onSync}
            disabled={disabled}
          >
            <RefreshCw className={syncing ? "animate-spin" : ""} size={16} aria-hidden="true" />
          </Button>

          <details
            ref={syncOptionsPopover.detailsRef}
            className="users-group-sync-options"
            aria-disabled={disabled}
            onToggle={syncOptionsPopover.onToggle}
          >
            <summary
              ref={syncOptionsPopover.summaryRef}
              aria-controls={syncOptionsPopover.contentId}
              aria-disabled={disabled}
              aria-expanded={syncOptionsPopover.open}
              onClick={(event) => {
                if (disabled) event.preventDefault();
              }}
            >
              Elementi da sincronizzare
            </summary>
            <div id={syncOptionsPopover.contentId}>
              {syncOptions.map(([key, label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={settings[key] === true || (key === "sync_playstate" && settings[key] !== false)}
                    disabled={disabled || (key === "sync_resume" && settings.sync_playstate !== true)}
                    onChange={(event) => setField(key, event.target.checked)}
                  />
                  <span>{label}</span>
                </label>
              ))}
              <p>Visti, preferiti e playlist: la prima sincronizzazione unisce i dati, poi applica la direzione scelta.</p>
              <strong>Categorie impostazioni</strong>
              {userConfigurationCategories.map((category) => (
                <label key={category.id}>
                  <input
                    type="checkbox"
                    checked={settings.config_categories?.includes(category.id) || false}
                    disabled={disabled || settings.sync_config !== true}
                    onChange={() => toggleCategory(category.id)}
                  />
                  <span>{category.label}</span>
                </label>
              ))}
            </div>
          </details>

          <GroupSyncStatus group={group} />
        </div>
      ) : <GroupSyncStatus group={group} className="users-group-sync-status--idle" />}
    </div>
  );
}

export { GroupSyncControls };
