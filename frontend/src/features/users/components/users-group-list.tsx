import { UsersRound } from "@/components/ui/icons";

import { UsersGroupCard } from "@/features/users/components/users-group-card";
import type { UserIconConfig } from "@/features/user-icons/types";
import type { EmbyUser, EmbyUserGroup, GroupSyncSettings } from "@/features/users/types";

type UsersGroupListProps = {
  groups: EmbyUserGroup[];
  selected: Set<string>;
  iconConfig: UserIconConfig;
  iconRevision: number;
  isGroupIconSaving: (group: EmbyUserGroup) => boolean;
  onToggle: (user: EmbyUser) => void;
  onToggleRemote: (user: EmbyUser) => void;
  onToggleDownload: (user: EmbyUser) => void;
  onConfigure: (group: EmbyUserGroup) => void;
  onSettings: (group: EmbyUserGroup) => void;
  onPassword: (group: EmbyUserGroup) => void;
  onRename: (group: EmbyUserGroup) => void;
  onDelete: (group: EmbyUserGroup) => void;
  onIconProfileChange: (group: EmbyUserGroup, profileId: string) => void;
  onUserPassword: (group: EmbyUserGroup, user: EmbyUser) => void;
  onUserSettings: (user: EmbyUser) => void;
  onUserRename: (user: EmbyUser) => void;
  onUserClone: (user: EmbyUser) => void;
  onUserDelete: (user: EmbyUser) => void;
  onUserUnlink: (user: EmbyUser) => void;
  onSetLeader: (group: EmbyUserGroup, user: EmbyUser) => void;
  onUserDetails: (user: EmbyUser) => void;
  onSaveSyncSettings: (group: EmbyUserGroup, settings: GroupSyncSettings) => Promise<void>;
  onSync: (group: EmbyUserGroup) => void;
  isGroupSyncing: (group: EmbyUserGroup) => boolean;
  isGroupSettingsSaving: (group: EmbyUserGroup) => boolean;
  groupSyncError: (group: EmbyUserGroup) => string | undefined;
  groupSettingsError: (group: EmbyUserGroup) => string | undefined;
  isUserChanging: (user: EmbyUser) => boolean;
  showHeading?: boolean;
};

function UsersGroupList({
  groups,
  selected,
  iconConfig,
  iconRevision,
  isGroupIconSaving,
  onToggle,
  onToggleRemote,
  onToggleDownload,
  onConfigure,
  onSettings,
  onPassword,
  onRename,
  onDelete,
  onIconProfileChange,
  onUserPassword,
  onUserSettings,
  onUserRename,
  onUserClone,
  onUserDelete,
  onUserUnlink,
  onSetLeader,
  onUserDetails,
  onSaveSyncSettings,
  onSync,
  isGroupSyncing,
  isGroupSettingsSaving,
  groupSyncError,
  groupSettingsError,
  isUserChanging,
  showHeading = true,
}: UsersGroupListProps) {
  return (
    <section className="users-group-list" {...(showHeading ? { "aria-labelledby": "users-group-list-title" } : { "aria-label": "Elenco gruppi utenti" })}>
      {showHeading ? <header className="users-list-heading">
        <div>
          <h2 id="users-group-list-title" className="contextual-heading" title="Gestione quotidiana"><UsersRound size={18} aria-hidden="true" /> Gruppi utenti</h2>
        </div>
        <span>{groups.length} {groups.length === 1 ? "gruppo" : "gruppi"}</span>
      </header> : null}

      {!groups.length ? <p className="users-empty">Nessun utente corrisponde ai filtri scelti.</p> : null}

      <div className="users-group-stack">
        {groups.map((group) => (
          <UsersGroupCard
            key={group.id}
            group={group}
            selected={selected}
            iconConfig={iconConfig}
            iconRevision={iconRevision}
            iconSaving={isGroupIconSaving(group)}
            onToggle={onToggle}
            onToggleRemote={onToggleRemote}
            onToggleDownload={onToggleDownload}
            onConfigure={() => onConfigure(group)}
            onSettings={() => onSettings(group)}
            onPassword={() => onPassword(group)}
            onRename={() => onRename(group)}
            onDelete={() => onDelete(group)}
            onIconProfileChange={(profileId) => onIconProfileChange(group, profileId)}
            onUserPassword={(user) => onUserPassword(group, user)}
            onUserSettings={onUserSettings}
            onUserRename={onUserRename}
            onUserClone={onUserClone}
            onUserDelete={onUserDelete}
            onUserUnlink={onUserUnlink}
            onSetLeader={(user) => onSetLeader(group, user)}
            onUserDetails={onUserDetails}
            onSaveSyncSettings={(settings) => onSaveSyncSettings(group, settings)}
            onSync={() => onSync(group)}
            syncing={isGroupSyncing(group)}
            savingSyncSettings={isGroupSettingsSaving(group)}
            syncError={groupSyncError(group)}
            settingsError={groupSettingsError(group)}
            isUserChanging={isUserChanging}
          />
        ))}
      </div>
    </section>
  );
}

export { UsersGroupList };
