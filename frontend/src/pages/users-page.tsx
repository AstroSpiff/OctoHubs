import { Star, UsersRound } from "@/components/ui/icons";
import { useCallback, useMemo, useState } from "react";

import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";
import { SettingsEditorDialog } from "@/features/user-settings/components/settings-editor-dialog";
import { BulkSettingsDialog } from "@/features/users/components/bulk-settings-dialog";
import { UsersSelectionActions } from "@/features/users/components/users-selection-actions";
import type { SettingsTarget } from "@/features/user-settings/types";
import { useUserIcons } from "@/features/user-icons/use-user-icons";
import { CloneUserDialog } from "@/features/users/components/clone-user-dialog";
import { CreateUserDialog } from "@/features/users/components/create-user-dialog";
import { DangerConfirmDialog } from "@/features/users/components/danger-confirm-dialog";
import { GroupSyncSettingsDialog } from "@/features/users/components/group-sync-settings-dialog";
import { LinkUsersDialog } from "@/features/users/components/link-users-dialog";
import { NameDialog } from "@/features/users/components/name-dialog";
import { PasswordDialog } from "@/features/users/components/password-dialog";
import { UserDetailsDialog } from "@/features/users/components/user-details-dialog";
import { UsersGroupList } from "@/features/users/components/users-group-list";
import { UserIconManagementSection } from "@/features/user-icons/components/user-icon-management-section";
import { userAvatarUrl } from "@/features/user-icons/presentation";
import type { UserIconConfig } from "@/features/user-icons/types";
import { UsersToolbar } from "@/features/users/components/users-toolbar";
import { UsersOperationsCenter } from "@/features/users/components/users-operations-center";
import { linkSelectionsFromGroups } from "@/features/users/link-user-association";
import {
  groupIconBindingTargets,
  hasPendingGroupIconBinding,
} from "@/features/users/group-icon-bindings";
import { isUserOperationPending } from "@/features/users/user-operation-state";
import { usePendingGroupIds, usePendingIds } from "@/features/users/use-pending-group-ids";
import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";
import { clearVisibleUserSelection, defaultUsersFilters, isLeaderOrStandalone, replaceVisibleUserSelection, userSelectionKey, visibleUserGroups } from "@/features/users/presentation";
import type { BulkCloneInput, EmbyUser, EmbyUserGroup, GroupSyncSettings, LinkUserSelection, LinkUsersInput, PasswordTarget, UsersFilters } from "@/features/users/types";
import { useUsers } from "@/features/users/use-users";
import { BulkClonePartialError, UserActionPartialError } from "@/features/users/api";

type RenameTarget = { kind: "group"; group: EmbyUserGroup } | { kind: "user"; user: EmbyUser };
type DeleteTarget = { kind: "group"; group: EmbyUserGroup } | { kind: "user"; user: EmbyUser };
type UsersDraftScope = "bulkSettings" | "clone" | "create" | "groupSync" | "iconProfile" | "link" | "name" | "password" | "settings";

const emptyIconConfig: UserIconConfig = { profiles: [], matrix: {}, bindings: {} };

function UsersPage() {
  const confirmation = useConfirmationDialog();
  const [filters, setFilters] = useState<UsersFilters>(defaultUsersFilters);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [configuredGroup, setConfiguredGroup] = useState<EmbyUserGroup | null>(null);
  const [settingsTarget, setSettingsTarget] = useState<SettingsTarget | null>(null);
  const [passwordTarget, setPasswordTarget] = useState<PasswordTarget | null>(null);
  const [renameTarget, setRenameTarget] = useState<RenameTarget | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [cloneSources, setCloneSources] = useState<EmbyUser[]>([]);
  const [cloneRetryJobs, setCloneRetryJobs] = useState<BulkCloneInput["retryJobs"]>();
  const [createRetryServerIds, setCreateRetryServerIds] = useState<string[]>([]);
  const [bulkSettingsUsers, setBulkSettingsUsers] = useState<EmbyUser[]>([]);
  const [linkSelections, setLinkSelections] = useState<LinkUserSelection[]>([]);
  const [detailsUser, setDetailsUser] = useState<EmbyUser | null>(null);
  const [accessErrors, setAccessErrors] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<UsersDraftScope, boolean>>({
    bulkSettings: false,
    clone: false,
    create: false,
    groupSync: false,
    iconProfile: false,
    link: false,
    name: false,
    password: false,
    settings: false,
  });
  const users = useUsers();
  const icons = useUserIcons();
  const pendingGroupSettings = usePendingGroupIds();
  const groupSyncOperations = useKeyedOperationState();
  const pendingRemoteAccess = usePendingIds();
  const pendingDownloadAccess = usePendingIds();
  const leaderOperations = useKeyedOperationState();
  const unlinkOperations = useKeyedOperationState();
  const dashboard = users.dashboard.data || { groups: [], servers: [] };
  const iconConfig = icons.config.data || emptyIconConfig;
  const activeConfiguredGroup = configuredGroup
    ? dashboard.groups.find((group) => group.id === configuredGroup.id) || configuredGroup
    : null;
  const groups = useMemo(() => visibleUserGroups(dashboard.groups, filters, iconConfig.bindings), [dashboard.groups, filters, iconConfig.bindings]);
  const allUsers = dashboard.groups.flatMap((group) => group.users);
  const visibleUsers = groups.flatMap((group) => group.users);
  const selectedUsers = allUsers.filter((user) => selected.has(userSelectionKey(user)));
  const selectedVisibleUsers = visibleUsers.filter((user) => selected.has(userSelectionKey(user)));
  const selectedHiddenCount = selectedUsers.length - selectedVisibleUsers.length;
  const leaders = groups.flatMap((group) => group.users.filter((user) => isLeaderOrStandalone(group, user)));
  const selectedLeaderCount = leaders.filter((user) => selected.has(userSelectionKey(user))).length;
  const detailsUserIsOwner = detailsUser !== null && dashboard.groups.some(
    (group) => group.is_owners && group.users.some((user) => userSelectionKey(user) === userSelectionKey(detailsUser)),
  );
  const detailsUserGroup = detailsUser
    ? dashboard.groups.find((group) =>
        group.users.some(
          (user) => userSelectionKey(user) === userSelectionKey(detailsUser),
        ),
      )
    : undefined;
  const detailsUserAvatarUrl = detailsUser && detailsUserGroup
    ? userAvatarUrl(
        detailsUserGroup,
        detailsUser,
        iconConfig,
        icons.config.dataUpdatedAt,
      )
    : undefined;
  const mutationError = users.link.error;
  const hasUnsavedDrafts = Object.values(drafts).some(Boolean);
  useBeforeUnloadWarning(hasUnsavedDrafts);
  useUnsavedChangesNavigationGuard(hasUnsavedDrafts, confirmation.confirm);
  const updateDraft = useCallback((scope: UsersDraftScope, dirty: boolean) => {
    setDrafts((current) => current[scope] === dirty ? current : { ...current, [scope]: dirty });
  }, []);
  const updateBulkSettingsDirty = useCallback((dirty: boolean) => updateDraft("bulkSettings", dirty), [updateDraft]);
  const updateCloneDirty = useCallback((dirty: boolean) => updateDraft("clone", dirty), [updateDraft]);
  const updateCreateDirty = useCallback((dirty: boolean) => updateDraft("create", dirty), [updateDraft]);
  const updateGroupSyncDirty = useCallback((dirty: boolean) => updateDraft("groupSync", dirty), [updateDraft]);
  const updateIconProfileDirty = useCallback((dirty: boolean) => updateDraft("iconProfile", dirty), [updateDraft]);
  const updateLinkDirty = useCallback((dirty: boolean) => updateDraft("link", dirty), [updateDraft]);
  const updateNameDirty = useCallback((dirty: boolean) => updateDraft("name", dirty), [updateDraft]);
  const updatePasswordDirty = useCallback((dirty: boolean) => updateDraft("password", dirty), [updateDraft]);
  const updateSettingsDirty = useCallback((dirty: boolean) => updateDraft("settings", dirty), [updateDraft]);
  const isUserChanging = useCallback((user: EmbyUser) => pendingRemoteAccess.pendingIds.has(userSelectionKey(user)) || pendingDownloadAccess.pendingIds.has(userSelectionKey(user)) || isUserOperationPending(user, {
    unlink: unlinkOperations.pendingKeys.has(userSelectionKey(user)) ? user : undefined,
    rename: users.userRename.isPending ? users.userRename.variables : undefined,
    password: users.password.isPending ? users.password.variables : undefined,
    delete: users.removeUser.isPending ? users.removeUser.variables : undefined,
    clone: users.clone.isPending ? users.clone.variables : undefined,
    applySettings: users.settingsApply.isPending ? users.settingsApply.variables : undefined,
    leader: leaderOperations.pendingKeys.has(userSelectionKey(user)) ? { user } : undefined,
  }), [
    users.clone.isPending,
    users.clone.variables,
    pendingDownloadAccess.pendingIds,
    pendingRemoteAccess.pendingIds,
    leaderOperations.pendingKeys,
    users.password.isPending,
    users.password.variables,
    users.removeUser.isPending,
    users.removeUser.variables,
    users.settingsApply.isPending,
    users.settingsApply.variables,
    unlinkOperations.pendingKeys,
    users.userRename.isPending,
    users.userRename.variables,
  ]);

  async function toggleRemoteAccess(user: EmbyUser) {
    const key = userSelectionKey(user);
    if (!pendingRemoteAccess.begin(key)) return;
    const errorKey = `remote:${key}`;
    setAccessErrors((current) => {
      const next = { ...current };
      delete next[errorKey];
      return next;
    });
    try {
      await users.remoteAccess.mutateAsync(user);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Errore sconosciuto";
      setAccessErrors((current) => ({
        ...current,
        [errorKey]: `${user.name} — accesso remoto: ${message}`,
      }));
    } finally {
      pendingRemoteAccess.finish(key);
    }
  }

  async function toggleDownloadAccess(user: EmbyUser) {
    const key = userSelectionKey(user);
    if (!pendingDownloadAccess.begin(key)) return;
    const errorKey = `download:${key}`;
    setAccessErrors((current) => {
      const next = { ...current };
      delete next[errorKey];
      return next;
    });
    try {
      await users.downloadAccess.mutateAsync(user);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Errore sconosciuto";
      setAccessErrors((current) => ({
        ...current,
        [errorKey]: `${user.name} — download: ${message}`,
      }));
    } finally {
      pendingDownloadAccess.finish(key);
    }
  }

  function updateFilters(updates: Partial<UsersFilters>) {
    setFilters((current) => ({ ...current, ...updates }));
  }

  function toggleUser(user: EmbyUser) {
    const key = userSelectionKey(user);
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function selectVisibleUsers(items: EmbyUser[]) {
    setSelected((current) => replaceVisibleUserSelection(current, visibleUsers, items));
  }

  function deselectVisibleUsers() {
    setSelected((current) => clearVisibleUserSelection(current, visibleUsers));
  }

  function openLinkSelected() {
    if (selectedUsers.length < 2) return;
    users.link.reset();
    setLinkSelections(linkSelectionsFromGroups(dashboard.groups, selected));
  }

  function linkSelected(input: LinkUsersInput) {
    users.link.mutate(input, {
      onSuccess: () => {
        setLinkSelections([]);
        setSelected(new Set());
      },
    });
  }

  function create(input: { username: string; password: string; serverIds: string[]; linkGroup: boolean; presetId?: string | null }) {
    users.create.mutate(input, {
      onSuccess: () => { setCreateRetryServerIds([]); setCreating(false); },
      onError: (error) => {
        if (!(error instanceof UserActionPartialError)) return;
        const outcome = error.outcome.result || error.outcome;
        const failures = Array.isArray(outcome.failed) ? outcome.failed : [];
        setCreateRetryServerIds(failures.flatMap((failure) =>
          typeof failure === "string" || !failure.server_id ? [] : [failure.server_id],
        ));
      },
    });
  }

  function saveGroupSettings(settings: GroupSyncSettings) {
    if (!activeConfiguredGroup || !pendingGroupSettings.begin(activeConfiguredGroup.id)) return;
    const groupId = activeConfiguredGroup.id;
    users.groupSettings.mutate(
      { group_id: groupId, ...settings },
      {
        onSuccess: () => setConfiguredGroup(null),
        onSettled: () => pendingGroupSettings.finish(groupId),
      },
    );
  }

  async function saveInlineGroupSettings(group: EmbyUserGroup, settings: GroupSyncSettings) {
    if (!pendingGroupSettings.begin(group.id)) return;
    const groupId = group.id;
    try {
      await users.groupSettings.mutateAsync({ group_id: groupId, ...settings });
    } finally {
      pendingGroupSettings.finish(groupId);
    }
  }

  function syncGroup(group: EmbyUserGroup) {
    if (group.last_sync_status === "running" || groupSyncOperations.isPending(group.id)) return;
    const groupId = group.id;
    groupSyncOperations.begin([groupId]);
    void users.groupSync.mutateAsync(groupId).catch((error: unknown) => {
      groupSyncOperations.fail([groupId], error);
    }).finally(() => groupSyncOperations.finish([groupId]));
  }

  function saveName(name: string) {
    if (!renameTarget) return;
    if (renameTarget.kind === "group") users.groupRename.mutate({ groupId: renameTarget.group.id, name }, { onSuccess: () => setRenameTarget(null) });
    else users.userRename.mutate({ user: renameTarget.user, name }, { onSuccess: () => setRenameTarget(null) });
  }

  function deleteCurrentTarget(expectedName: string) {
    if (!deleteTarget) return;
    if (deleteTarget.kind === "group") users.removeGroup.mutate({ group: deleteTarget.group, expectedName }, { onSuccess: () => setDeleteTarget(null) });
    else users.removeUser.mutate({ user: deleteTarget.user, expectedName }, { onSuccess: () => setDeleteTarget(null) });
  }

  function savePassword(password: string) {
    if (passwordTarget) users.password.mutate({ target: passwordTarget, password }, { onSuccess: () => setPasswordTarget(null) });
  }

  function cloneUsers(input: BulkCloneInput) {
    users.clone.mutate({ ...input, retryJobs: cloneRetryJobs }, {
      onSuccess: () => { setCloneRetryJobs(undefined); setCloneSources([]); },
      onError: (error) => {
        if (error instanceof BulkClonePartialError) {
          setCloneRetryJobs(error.result.failed.map(({ source, targetServerId }) => ({ source: { user: source, newUsername: input.sources.find((item) => item.user.server_id === source.server_id && item.user.user_id === source.user_id)?.newUsername || source.name, linkGroup: input.sources.find((item) => item.user.server_id === source.server_id && item.user.user_id === source.user_id)?.linkGroup || false }, targetServerId })));
        }
      },
    });
  }

  async function unlinkUser(user: EmbyUser) {
    if (!await confirmation.confirm({ title: "Dissocia utente", description: `Dissociare ${user.name} dal gruppo?`, confirmLabel: "Dissocia", tone: "danger" })) return;
    const targetKey = userSelectionKey(user);
    if (unlinkOperations.isPending(targetKey)) return;
    unlinkOperations.begin([targetKey]);
    try {
      await users.unlink.mutateAsync(user);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Errore sconosciuto";
      unlinkOperations.fail([targetKey], new Error(`${user.name} — dissociazione: ${message}`));
    } finally {
      unlinkOperations.finish([targetKey]);
    }
  }

  async function setLeader(group: EmbyUserGroup, user: EmbyUser) {
    if (!await confirmation.confirm({ title: "Imposta leader", description: `Impostare ${user.name} come leader del gruppo ${group.name}?`, confirmLabel: "Imposta leader" })) return;
    const targetKey = userSelectionKey(user);
    if (leaderOperations.isPending(targetKey)) return;
    leaderOperations.begin([targetKey]);
    try {
      await users.leader.mutateAsync({ group, user });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Errore sconosciuto";
      leaderOperations.fail([targetKey], new Error(`${user.name} — leader: ${message}`));
    } finally {
      leaderOperations.finish([targetKey]);
    }
  }

  function saveGroupIconProfile(group: EmbyUserGroup, profileId: string) {
    const targets = groupIconBindingTargets(group, profileId);
    if (targets.length && !hasPendingGroupIconBinding(group, icons.bindingOperations.pendingKeys)) {
      icons.bindings.mutate(targets);
    }
  }

  return (
    <WorkspacePage className="emby-users-page">
      <WorkspaceHeading
        level="section"
        title="Utenti"
        description="Gestisci gruppi, accessi, permessi, sincronizzazione e identità visive degli account Emby."
      />
      {users.dashboard.error ? <div className="inline-alert inline-alert--error" role="alert">{users.dashboard.error.message}</div> : null}
      {mutationError ? <div className="inline-alert inline-alert--error" role="alert">{mutationError.message}</div> : null}
      {Object.entries(accessErrors).map(([key, message]) => (
        <div key={key} className="inline-alert inline-alert--error" role="alert">{message}</div>
      ))}
      {([[
        "leader",
        leaderOperations.errors,
      ], [
        "unlink",
        unlinkOperations.errors,
      ]] as const).flatMap(([scope, errors]) =>
        Object.entries(errors).map(([key, message]) => [scope, key, message] as const)
      ).map(([scope, key, message]) => (
        <div key={`${scope}:${key}`} className="inline-alert inline-alert--error" role="alert">{message}</div>
      ))}
      {Object.entries(icons.bindingOperations.errors).map(([key, message]) => (
        <div key={key} className="inline-alert inline-alert--error" role="alert">Associazione profilo icona non riuscita: {message}</div>
      ))}
      <UsersSelectionActions selectedCount={selectedUsers.length} hiddenCount={selectedHiddenCount} onLink={openLinkSelected} onBulkSettings={() => setBulkSettingsUsers(selectedUsers)} onBulkClone={() => setCloneSources(selectedUsers)} onDeselect={() => setSelected(new Set())} />
      <section className="users-workspace" aria-labelledby="users-groups-title">
        <UsersToolbar data={dashboard} iconProfiles={iconConfig.profiles} filters={filters} selection={{ visibleCount: visibleUsers.length, selectedVisibleCount: selectedVisibleUsers.length, leaderCount: leaders.length, selectedLeaderCount }} refreshing={users.dashboard.isFetching} onChange={updateFilters} onSelectAll={() => selectVisibleUsers(visibleUsers)} onSelectLeaders={() => selectVisibleUsers(leaders)} onDeselect={deselectVisibleUsers} onCreate={() => setCreating(true)} onRefresh={() => void users.dashboard.refetch()} />
        <div className="users-groups-section">
          <WorkspaceHeading
            className="users-groups-heading"
            level="subsection"
            leading={<UsersRound size={19} aria-hidden="true" />}
            title="Gruppi utenti"
            titleId="users-groups-title"
            description={<>Gestisci utenti, permessi e sincronizzazione tra gli account associati. L&apos;utente con la <span className="users-leader-symbol" aria-label="simbolo del leader"><Star size={14} aria-hidden="true" /></span> è il Leader del gruppo.</>}
          />
          <UsersGroupList
            groups={groups}
            selected={selected}
            iconConfig={iconConfig}
            iconRevision={icons.config.dataUpdatedAt}
            isGroupIconSaving={(group) =>
              hasPendingGroupIconBinding(group, icons.bindingOperations.pendingKeys)
            }
            onToggle={toggleUser}
            onToggleRemote={(user) => void toggleRemoteAccess(user)}
            onToggleDownload={(user) => void toggleDownloadAccess(user)}
            onConfigure={setConfiguredGroup}
            onSettings={(group) => setSettingsTarget({ scope: "group", groupId: group.id, name: group.name, mismatchCount: group.settings_mismatch_count || 0 })}
            onPassword={(group) => setPasswordTarget({ scope: "group", groupId: group.id, name: group.name, mismatchCount: group.password_mismatch_count || 0 })}
            onRename={(group) => setRenameTarget({ kind: "group", group })}
            onDelete={(group) => setDeleteTarget({ kind: "group", group })}
            onIconProfileChange={saveGroupIconProfile}
            onUserPassword={(_, user) => setPasswordTarget({ scope: "user", serverId: user.server_id, userId: user.user_id, name: user.name, hasEmbyPassword: user.has_password, mismatch: user.password_mismatch })}
            onUserSettings={(user) => setSettingsTarget({ scope: "user", serverId: user.server_id, userId: user.user_id, name: user.name, mismatch: user.settings_mismatch })}
            onUserRename={(user) => setRenameTarget({ kind: "user", user })}
            onUserClone={(user) => setCloneSources([user])}
            onUserDelete={(user) => setDeleteTarget({ kind: "user", user })}
            onUserUnlink={(user) => void unlinkUser(user)}
            onSetLeader={(group, user) => void setLeader(group, user)}
            onUserDetails={setDetailsUser}
            onSaveSyncSettings={saveInlineGroupSettings}
            onSync={syncGroup}
            isGroupSyncing={(group) => groupSyncOperations.pendingKeys.has(group.id) || group.last_sync_status === "running"}
            isGroupSettingsSaving={(group) => pendingGroupSettings.pendingIds.has(group.id)}
            groupSyncError={(group) => groupSyncOperations.errors[group.id]}
            groupSettingsError={(group) => users.groupSettings.variables?.group_id === group.id ? users.groupSettings.error?.message : undefined}
            isUserChanging={isUserChanging}
            showHeading={false}
          />
        </div>
      </section>
      <UserIconManagementSection icons={icons} servers={dashboard.servers} onDirtyChange={updateIconProfileDirty} />
      <CreateUserDialog open={creating} servers={dashboard.servers} creating={users.create.isPending} mutationError={users.create.error?.message} retryServerIds={createRetryServerIds} onClose={() => { users.create.reset(); setCreateRetryServerIds([]); setCreating(false); }} onCreate={create} onDirtyChange={updateCreateDirty} />
      <LinkUsersDialog selections={linkSelections} linking={users.link.isPending} error={users.link.error?.message} onClose={() => setLinkSelections([])} onLink={linkSelected} onDirtyChange={updateLinkDirty} />
      {activeConfiguredGroup ? (
        <GroupSyncSettingsDialog
          group={activeConfiguredGroup}
          saving={pendingGroupSettings.pendingIds.has(activeConfiguredGroup.id)}
          syncing={groupSyncOperations.pendingKeys.has(activeConfiguredGroup.id) || activeConfiguredGroup.last_sync_status === "running"}
          error={users.groupSettings.variables?.group_id === activeConfiguredGroup.id ? users.groupSettings.error?.message : undefined}
          onClose={() => setConfiguredGroup(null)}
          onSave={saveGroupSettings}
          onDirtyChange={updateGroupSyncDirty}
        />
      ) : null}
      <SettingsEditorDialog target={settingsTarget} onClose={() => setSettingsTarget(null)} onSaved={users.refresh} onDirtyChange={updateSettingsDirty} />
      <PasswordDialog target={passwordTarget} saving={users.password.isPending} mutationError={users.password.error?.message} onClose={() => { users.password.reset(); setPasswordTarget(null); }} onSave={savePassword} onDirtyChange={updatePasswordDirty} />
      <NameDialog open={renameTarget !== null} title={renameTarget?.kind === "group" ? "Rinomina gruppo" : "Rinomina utente"} label={renameTarget?.kind === "group" ? "Nome gruppo" : "Nome utente"} initialValue={renameTarget?.kind === "group" ? renameTarget.group.name : renameTarget?.user.name || ""} saving={users.userRename.isPending || users.groupRename.isPending} mutationError={renameTarget?.kind === "group" ? users.groupRename.error?.message : users.userRename.error?.message} onClose={() => { users.userRename.reset(); users.groupRename.reset(); setRenameTarget(null); }} onSave={saveName} onDirtyChange={updateNameDirty} />
      <DangerConfirmDialog open={deleteTarget !== null} title={deleteTarget?.kind === "group" ? "Elimina tutti gli utenti del gruppo" : "Elimina utente"} description={deleteTarget?.kind === "group" ? `Verranno eliminati da Emby tutti gli utenti del gruppo ${deleteTarget.group.name}.` : `Verrà eliminato da Emby l'utente ${deleteTarget?.user.name || ""}.`} expectedName={deleteTarget?.kind === "group" ? deleteTarget.group.name : deleteTarget?.user.name || ""} confirming={users.removeUser.isPending || users.removeGroup.isPending} mutationError={deleteTarget?.kind === "group" ? users.removeGroup.error?.message : users.removeUser.error?.message} onClose={() => { users.removeUser.reset(); users.removeGroup.reset(); setDeleteTarget(null); }} onConfirm={deleteCurrentTarget} />
      <BulkSettingsDialog users={bulkSettingsUsers} saving={users.settingsApply.isPending} mutationError={users.settingsApply.error?.message} onClose={() => { users.settingsApply.reset(); setBulkSettingsUsers([]); }} onApply={(input) => users.settingsApply.mutate(input, { onSuccess: () => setBulkSettingsUsers([]) })} onDirtyChange={updateBulkSettingsDirty} />
      <CloneUserDialog users={cloneSources} groups={dashboard.groups} servers={dashboard.servers} cloning={users.clone.isPending} mutationError={users.clone.error?.message} onClose={() => { users.clone.reset(); setCloneRetryJobs(undefined); setCloneSources([]); }} onClone={cloneUsers} onDirtyChange={updateCloneDirty} />
      <UserDetailsDialog
        user={detailsUser}
        avatarUrl={detailsUserAvatarUrl}
        isOwner={detailsUserIsOwner}
        changing={detailsUser ? isUserChanging(detailsUser) : false}
        onClose={() => setDetailsUser(null)}
        onRename={() => {
          if (!detailsUser) return;
          setDetailsUser(null);
          setRenameTarget({ kind: "user", user: detailsUser });
        }}
        onPassword={() => {
          if (!detailsUser) return;
          setDetailsUser(null);
          setPasswordTarget({ scope: "user", serverId: detailsUser.server_id, userId: detailsUser.user_id, name: detailsUser.name, hasEmbyPassword: detailsUser.has_password, mismatch: detailsUser.password_mismatch });
        }}
        onClone={() => {
          if (!detailsUser) return;
          setDetailsUser(null);
          setCloneSources([detailsUser]);
        }}
        onDelete={() => {
          if (!detailsUser) return;
          setDetailsUser(null);
          setDeleteTarget({ kind: "user", user: detailsUser });
        }}
      />
      <UsersOperationsCenter />
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { UsersPage };
