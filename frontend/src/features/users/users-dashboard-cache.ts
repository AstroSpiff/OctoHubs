import type {
  EmbyUser,
  EmbyUserGroup,
  SaveGroupSyncSettingsInput,
  UsersDashboard,
} from "@/features/users/types";

function updateDashboardUser(
  dashboard: UsersDashboard,
  target: EmbyUser,
  changes: Partial<EmbyUser>,
): UsersDashboard {
  return {
    ...dashboard,
    groups: dashboard.groups.map((group) => ({
      ...group,
      users: group.users.map((user) =>
        sameUser(user, target) ? { ...user, ...changes } : user,
      ),
    })),
  };
}

function updateDashboardGroupSettings(
  dashboard: UsersDashboard,
  input: SaveGroupSyncSettingsInput,
): UsersDashboard {
  const { group_id: groupId, ...settings } = input;
  return updateDashboardGroup(dashboard, groupId, settings);
}

function updateDashboardGroupSyncStatus(
  dashboard: UsersDashboard,
  groupId: string,
  status: string,
  message: string,
): UsersDashboard {
  return updateDashboardGroup(dashboard, groupId, {
    last_sync_status: status,
    last_sync_message: message,
  });
}

function updateDashboardLeader(
  dashboard: UsersDashboard,
  groupId: string,
  leader: EmbyUser,
): UsersDashboard {
  return {
    ...dashboard,
    groups: dashboard.groups.map((group) =>
      group.id !== groupId
        ? group
        : {
            ...group,
            users: group.users.map((user) => ({
              ...user,
              is_leader: sameUser(user, leader),
            })),
          },
    ),
  };
}

function restoreDashboardGroupSettings(
  dashboard: UsersDashboard,
  previous: UsersDashboard,
  input: SaveGroupSyncSettingsInput,
): UsersDashboard {
  const previousGroup = previous.groups.find((group) => group.id === input.group_id);
  if (!previousGroup) return dashboard;
  const { group_id: groupId, ...submittedSettings } = input;
  const restored = Object.fromEntries(
    Object.keys(submittedSettings).map((key) => [
      key,
      previousGroup[key as keyof EmbyUserGroup],
    ]),
  ) as Partial<EmbyUserGroup>;
  return updateDashboardGroup(dashboard, groupId, restored);
}

function restoreDashboardGroupSyncStatus(
  dashboard: UsersDashboard,
  previous: UsersDashboard,
  groupId: string,
): UsersDashboard {
  const previousGroup = previous.groups.find((group) => group.id === groupId);
  if (!previousGroup) return dashboard;
  return updateDashboardGroup(dashboard, groupId, {
    last_sync_status: previousGroup.last_sync_status,
    last_sync_message: previousGroup.last_sync_message,
  });
}

function restoreDashboardLeader(
  dashboard: UsersDashboard,
  previous: UsersDashboard,
  groupId: string,
): UsersDashboard {
  const previousGroup = previous.groups.find((group) => group.id === groupId);
  if (!previousGroup) return dashboard;
  const previousLeaders = new Map(
    previousGroup.users.map((user) => [
      `${user.server_id}:${user.user_id}`,
      user.is_leader,
    ]),
  );
  return {
    ...dashboard,
    groups: dashboard.groups.map((group) =>
      group.id !== groupId
        ? group
        : {
            ...group,
            users: group.users.map((user) => ({
              ...user,
              is_leader:
                previousLeaders.get(`${user.server_id}:${user.user_id}`) ??
                user.is_leader,
            })),
          },
    ),
  };
}

function updateDashboardGroup(
  dashboard: UsersDashboard,
  groupId: string,
  changes: Partial<EmbyUserGroup>,
): UsersDashboard {
  return {
    ...dashboard,
    groups: dashboard.groups.map((group) =>
      group.id === groupId ? { ...group, ...changes } : group,
    ),
  };
}

function sameUser(first: EmbyUser, second: EmbyUser) {
  return (
    first.server_id === second.server_id && first.user_id === second.user_id
  );
}

export {
  restoreDashboardGroupSettings,
  restoreDashboardGroupSyncStatus,
  restoreDashboardLeader,
  updateDashboardGroupSettings,
  updateDashboardGroupSyncStatus,
  updateDashboardLeader,
  updateDashboardUser,
};
