import { KeyRound, Link2, Pencil, RefreshCw, Repeat2, SlidersHorizontal, Star, Trash2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { GroupIconProfileSelect } from "@/features/users/components/group-icon-profile-select";
import { GroupSyncControls } from "@/features/users/components/group-sync-controls";
import { UserRow } from "@/features/users/components/user-row";
import { passwordPresentation, settingsPresentation, syncPresentation, userSelectionKey } from "@/features/users/presentation";
import { userAvatarUrl } from "@/features/user-icons/presentation";
import type { UserIconConfig } from "@/features/user-icons/types";
import type { EmbyUser, EmbyUserGroup, GroupSyncSettings } from "@/features/users/types";

type UsersGroupCardProps = {
  group: EmbyUserGroup;
  selected: Set<string>;
  iconConfig: UserIconConfig;
  iconRevision: number;
  iconSaving: boolean;
  onToggle: (user: EmbyUser) => void;
  onToggleRemote: (user: EmbyUser) => void;
  onToggleDownload: (user: EmbyUser) => void;
  onConfigure: () => void;
  onSettings: () => void;
  onPassword: () => void;
  onRename: () => void;
  onDelete: () => void;
  onIconProfileChange: (profileId: string) => void;
  onUserPassword: (user: EmbyUser) => void;
  onUserSettings: (user: EmbyUser) => void;
  onUserRename: (user: EmbyUser) => void;
  onUserClone: (user: EmbyUser) => void;
  onUserDelete: (user: EmbyUser) => void;
  onUserUnlink: (user: EmbyUser) => void;
  onSetLeader: (user: EmbyUser) => void;
  onUserDetails: (user: EmbyUser) => void;
  onSaveSyncSettings: (settings: GroupSyncSettings) => Promise<void>;
  onSync: () => void;
  syncing: boolean;
  savingSyncSettings: boolean;
  syncError?: string;
  settingsError?: string;
  isUserChanging: (user: EmbyUser) => boolean;
};

function UsersGroupCard({
  group,
  selected,
  iconConfig,
  iconRevision,
  iconSaving,
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
  syncing,
  savingSyncSettings,
  syncError,
  settingsError,
  isUserChanging,
}: UsersGroupCardProps) {
  const sync = syncPresentation(group);
  const groupBusy = syncing || savingSyncSettings;
  const settingsSyncing = syncing && group.sync_config === true;

  return (
    <article className={`users-group-card users-group-card--${sync.severity}`}>
      <header className="users-group-header">
        <div className="users-group-identity">
          <div className="users-group-title-row">
            <h4>{group.name}</h4>
            {!group.is_owners ? (
              <Button
                type="button"
                requiresWriteAccess
                variant="ghost"
                size="icon"
                className="users-group-rename"
                title="Rinomina gruppo"
                aria-label={`Rinomina gruppo ${group.name}`}
                onClick={onRename}
                disabled={groupBusy}
              >
                <Pencil size={14} aria-hidden="true" />
              </Button>
            ) : null}
            <GroupMemberCount group={group} />
          </div>
          <p>{group.is_linked ? "Gruppo associato" : group.is_owners ? "Proprietari" : "Utente singolo"}</p>
        </div>

        <WriteAction>
          <GroupSyncControls
            group={group}
            saving={savingSyncSettings}
            syncing={syncing}
            onSave={onSaveSyncSettings}
            onSync={onSync}
          />
        </WriteAction>

        <div className="users-group-controls">
          <WriteAction>
            <GroupIconProfileSelect
              group={group}
              profiles={iconConfig.profiles}
              bindings={iconConfig.bindings}
              saving={iconSaving || groupBusy}
              onChange={onIconProfileChange}
            />
          </WriteAction>
          <GroupActions
            group={group}
            syncing={syncing}
            busy={groupBusy}
            onPassword={onPassword}
            onSettings={onSettings}
            onConfigure={onConfigure}
            onSync={onSync}
            onDelete={onDelete}
          />
        </div>
      </header>

      {syncing ? <p className="users-group-message" role="status">Sincronizzazione in corso. Le azioni che cambiano il gruppo torneranno disponibili al termine.</p> : null}
      {settingsError ? <p className="users-group-message users-group-message--error" role="alert">Salvataggio impostazioni gruppo non riuscito: {settingsError}</p> : null}
      {syncError ? <p className="users-group-message users-group-message--error" role="alert">Avvio sincronizzazione non riuscito: {syncError}</p> : null}

      <div className="users-group-members">
        {group.users.map((user) => (
          <UserRow
            key={userSelectionKey(user)}
            user={user}
            avatarUrl={userAvatarUrl(group, user, iconConfig, iconRevision)}
            checked={selected.has(userSelectionKey(user))}
            linked={group.is_linked}
            isOwner={group.is_owners === true}
            onToggle={() => onToggle(user)}
            onToggleRemote={() => onToggleRemote(user)}
            onToggleDownload={() => onToggleDownload(user)}
            onPassword={() => onUserPassword(user)}
            onSettings={() => onUserSettings(user)}
            onRename={() => onUserRename(user)}
            onClone={() => onUserClone(user)}
            onDelete={() => onUserDelete(user)}
            onUnlink={() => onUserUnlink(user)}
            onMakeLeader={() => onSetLeader(user)}
            onDetails={() => onUserDetails(user)}
            changing={isUserChanging(user)}
            groupSyncing={syncing}
            settingsSyncing={settingsSyncing}
          />
        ))}
      </div>
    </article>
  );
}

function GroupActions({ group, syncing, busy, onPassword, onSettings, onConfigure, onSync, onDelete }: Pick<UsersGroupCardProps, "group" | "syncing" | "onPassword" | "onSettings" | "onConfigure" | "onSync" | "onDelete"> & { busy: boolean }) {
  const password = passwordPresentation(group);
  const settings = settingsPresentation(group);
  const passwordTitle = group.password_mismatch_count
    ? `${password.label}: ${group.password_mismatch_count} ${group.password_mismatch_count === 1 ? "utente non allineato" : "utenti non allineati"}`
    : password.label;
  const settingsTitle = group.settings_mismatch_count
    ? `${settings.label}: ${group.settings_mismatch_count} ${group.settings_mismatch_count === 1 ? "utente non allineato" : "utenti non allineati"}`
    : settings.label;

  return (
    <div className="users-group-actions">
      {!group.is_owners ? <Button type="button" requiresWriteAccess variant="ghost" size="icon" className={`users-group-action--${password.severity}`} title={passwordTitle} aria-label={`Gestisci password gruppo: ${passwordTitle}`} onClick={onPassword} disabled={busy}><KeyRound size={16} aria-hidden="true" /></Button> : null}
      {!group.is_owners ? <Button type="button" requiresWriteAccess variant="ghost" size="icon" className={`users-group-action--${settings.severity}`} title={settingsTitle} aria-label={`Gestisci impostazioni Emby gruppo: ${settingsTitle}`} onClick={onSettings} disabled={busy}><SlidersHorizontal size={16} aria-hidden="true" /></Button> : null}
      {group.is_linked ? <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Configura sincronizzazione" aria-label="Configura sincronizzazione" onClick={onConfigure} disabled={busy}><Repeat2 size={16} aria-hidden="true" /></Button> : null}
      {group.is_linked && !group.auto_sync ? <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Sincronizza gruppo adesso" aria-label="Sincronizza gruppo adesso" onClick={onSync} disabled={busy}><RefreshCw size={16} className={syncing ? "animate-spin" : ""} aria-hidden="true" /></Button> : null}
      {!group.is_owners ? <Button type="button" requiresWriteAccess variant="ghost" size="icon" className="users-group-delete" title="Elimina utenti del gruppo" aria-label="Elimina utenti del gruppo" onClick={onDelete} disabled={busy}><Trash2 size={16} aria-hidden="true" /></Button> : null}
    </div>
  );
}

function GroupMemberCount({ group }: { group: EmbyUserGroup }) {
  const count = group.users.length;
  const label = group.is_owners ? `${count} amministratori` : group.is_linked ? `${count} utenti associati` : `${count} utente${count === 1 ? "" : "i"}`;

  return (
    <span className={`users-group-member-count${group.is_owners ? " users-group-member-count--owners" : ""}`} title={label} aria-label={label}>
      {group.is_owners ? <Star size={13} aria-hidden="true" /> : group.is_linked ? <Link2 size={13} aria-hidden="true" /> : null}
      <span>{count}</span>
    </span>
  );
}

export { UsersGroupCard };
