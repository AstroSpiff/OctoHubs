import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { applySettingsToUsers, cloneUsers, createUsers, deleteGroupUsers, deleteUser, getUsersDashboard, linkUsers, renameGroup, renameUser, saveGroupSyncSettings, savePassword, setGroupLeader, syncUserGroup, toggleDownloadAccess, toggleRemoteAccess, unlinkUser } from "@/features/users/api";
import { useUsersRealtime } from "@/features/users/use-users-realtime";
import {
  updateDashboardGroupSettings,
  updateDashboardGroupSyncStatus,
  updateDashboardLeader,
  updateDashboardUser,
} from "@/features/users/users-dashboard-cache";
import type { UsersDashboard } from "@/features/users/types";

function useUsers() {
  const client = useQueryClient();
  const dashboard = useQuery({ queryKey: ["users-dashboard"], queryFn: getUsersDashboard, refetchInterval: 10_000 });
  const refresh = useCallback(() => client.invalidateQueries({ queryKey: ["users-dashboard"] }), [client]);
  const updateDashboard = useCallback(
    (update: (current: UsersDashboard) => UsersDashboard) => {
      client.setQueryData<UsersDashboard>(["users-dashboard"], (current) =>
        current ? update(current) : current,
      );
    },
    [client],
  );
  const updateDashboardOptimistically = useCallback(
    async (update: (current: UsersDashboard) => UsersDashboard) => {
      await client.cancelQueries({ queryKey: ["users-dashboard"] });
      updateDashboard(update);
    },
    [client, updateDashboard],
  );
  useUsersRealtime(refresh);
  const remoteAccess = useMutation({
    mutationFn: toggleRemoteAccess,
    onMutate: (user) => updateDashboardOptimistically((current) => updateDashboardUser(current, user, {
      enable_remote_access: !user.enable_remote_access,
      is_remote_disabled: user.enable_remote_access,
    })),
    onSettled: refresh,
  });
  const downloadAccess = useMutation({
    mutationFn: toggleDownloadAccess,
    onMutate: (user) => updateDashboardOptimistically((current) => updateDashboardUser(current, user, {
      enable_downloading: !user.enable_downloading,
    })),
    onSettled: refresh,
  });
  const groupSync = useMutation({
    mutationFn: syncUserGroup,
    onMutate: (groupId) => updateDashboardOptimistically((current) =>
      updateDashboardGroupSyncStatus(
        current,
        groupId,
        "running",
        "Sincronizzazione manuale avviata",
      ),
    ),
    onSettled: refresh,
  });
  const groupSettings = useMutation({
    mutationFn: saveGroupSyncSettings,
    onMutate: (input) => updateDashboardOptimistically((current) => updateDashboardGroupSettings(current, input)),
    onSettled: refresh,
  });
  const link = useMutation({ mutationFn: linkUsers, onSuccess: refresh });
  const leader = useMutation({
    mutationFn: ({ group, user }: { group: Parameters<typeof setGroupLeader>[0]; user: Parameters<typeof setGroupLeader>[1] }) => setGroupLeader(group, user),
    onMutate: ({ group, user }) => updateDashboardOptimistically((current) => updateDashboardLeader(current, group.id, user)),
    onSettled: refresh,
  });
  const unlink = useMutation({ mutationFn: unlinkUser, onSuccess: refresh });
  const userRename = useMutation({ mutationFn: renameUser, onSuccess: refresh });
  const groupRename = useMutation({ mutationFn: renameGroup, onSuccess: refresh });
  const password = useMutation({ mutationFn: savePassword, onSuccess: refresh });
  const removeUser = useMutation({ mutationFn: deleteUser, onSuccess: refresh });
  const removeGroup = useMutation({ mutationFn: deleteGroupUsers, onSuccess: refresh });
  const clone = useMutation({ mutationFn: cloneUsers, onSuccess: refresh });
  const settingsApply = useMutation({ mutationFn: applySettingsToUsers, onSuccess: refresh });
  const create = useMutation({ mutationFn: createUsers, onSuccess: refresh });
  return { dashboard, remoteAccess, downloadAccess, groupSync, groupSettings, link, leader, unlink, userRename, groupRename, password, removeUser, removeGroup, clone, settingsApply, create, refresh };
}

export { useUsers };
