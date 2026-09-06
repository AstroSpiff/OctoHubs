import { useCallback, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { applySettingsToUsers, cloneUsers, createUsers, deleteGroupUsers, deleteUser, getUsersDashboard, linkUsers, renameGroup, renameUser, saveGroupSyncSettings, savePassword, setGroupLeader, syncUserGroup, toggleDownloadAccess, toggleRemoteAccess, unlinkUser } from "@/features/users/api";
import { useUsersRealtime } from "@/features/users/use-users-realtime";
import { useSensitiveMutation } from "@/lib/use-sensitive-mutation";
import {
  restoreDashboardGroupSettings,
  restoreDashboardGroupSyncStatus,
  restoreDashboardLeader,
  updateDashboardGroupSettings,
  updateDashboardGroupSyncStatus,
  updateDashboardLeader,
  updateDashboardUser,
} from "@/features/users/users-dashboard-cache";
import type { UsersDashboard } from "@/features/users/types";

function useUsers() {
  const client = useQueryClient();
  const optimisticVersions = useRef(new Map<string, number>());
  const optimisticBases = useRef(new Map<string, UsersDashboard>());
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
  const beginVersionedOptimisticUpdate = useCallback(
    async (key: string, update: (current: UsersDashboard) => UsersDashboard) => {
      await client.cancelQueries({ queryKey: ["users-dashboard"] });
      const version = (optimisticVersions.current.get(key) || 0) + 1;
      optimisticVersions.current.set(key, version);
      const current = client.getQueryData<UsersDashboard>(["users-dashboard"]);
      if (current && !optimisticBases.current.has(key)) {
        optimisticBases.current.set(key, current);
      }
      const previous = optimisticBases.current.get(key);
      updateDashboard(update);
      return { key, previous, version };
    },
    [client, updateDashboard],
  );
  const rollbackVersionedOptimisticUpdate = useCallback(
    (
      context: { key: string; previous?: UsersDashboard; version: number } | undefined,
      restore: (current: UsersDashboard, previous: UsersDashboard) => UsersDashboard,
    ) => {
      if (
        !context?.previous ||
        optimisticVersions.current.get(context.key) !== context.version
      ) return;
      updateDashboard((current) => restore(current, context.previous as UsersDashboard));
    },
    [updateDashboard],
  );
  const completeVersionedOptimisticUpdate = useCallback(
    (context: { key: string; version: number } | undefined) => {
      if (
        context &&
        optimisticVersions.current.get(context.key) === context.version
      ) {
        optimisticBases.current.delete(context.key);
      }
    },
    [],
  );
  useUsersRealtime(refresh);
  const remoteAccess = useMutation({
    mutationFn: toggleRemoteAccess,
    onMutate: (user) => updateDashboardOptimistically((current) => updateDashboardUser(current, user, {
      enable_remote_access: !user.enable_remote_access,
      is_remote_disabled: user.enable_remote_access,
    })),
    onError: (_error, user) => updateDashboard((current) => updateDashboardUser(current, user, {
      enable_remote_access: user.enable_remote_access,
      is_remote_disabled: user.is_remote_disabled,
    })),
    onSettled: refresh,
  });
  const downloadAccess = useMutation({
    mutationFn: toggleDownloadAccess,
    onMutate: (user) => updateDashboardOptimistically((current) => updateDashboardUser(current, user, {
      enable_downloading: !user.enable_downloading,
    })),
    onError: (_error, user) => updateDashboard((current) => updateDashboardUser(current, user, {
      enable_downloading: user.enable_downloading,
    })),
    onSettled: refresh,
  });
  const groupSync = useMutation({
    mutationFn: syncUserGroup,
    onMutate: (groupId) => beginVersionedOptimisticUpdate(`sync:${groupId}`, (current) =>
      updateDashboardGroupSyncStatus(
        current,
        groupId,
        "running",
        "Sincronizzazione manuale avviata",
      ),
    ),
    onError: (_error, groupId, context) => rollbackVersionedOptimisticUpdate(
      context,
      (current, previous) => restoreDashboardGroupSyncStatus(current, previous, groupId),
    ),
    onSettled: (_data, _error, _variables, context) => {
      completeVersionedOptimisticUpdate(context);
      return refresh();
    },
  });
  const groupSettings = useMutation({
    mutationFn: saveGroupSyncSettings,
    onMutate: (input) => beginVersionedOptimisticUpdate(
      `settings:${input.group_id}`,
      (current) => updateDashboardGroupSettings(current, input),
    ),
    onError: (_error, input, context) => rollbackVersionedOptimisticUpdate(
      context,
      (current, previous) => restoreDashboardGroupSettings(current, previous, input),
    ),
    onSettled: (_data, _error, _input, context) => {
      completeVersionedOptimisticUpdate(context);
      return refresh();
    },
  });
  const link = useMutation({ mutationFn: linkUsers, onSuccess: refresh });
  const leader = useMutation({
    mutationFn: ({ group, user }: { group: Parameters<typeof setGroupLeader>[0]; user: Parameters<typeof setGroupLeader>[1] }) => setGroupLeader(group, user),
    onMutate: ({ group, user }) => beginVersionedOptimisticUpdate(
      `leader:${group.id}`,
      (current) => updateDashboardLeader(current, group.id, user),
    ),
    onError: (_error, { group }, context) => rollbackVersionedOptimisticUpdate(
      context,
      (current, previous) => restoreDashboardLeader(current, previous, group.id),
    ),
    onSettled: (_data, _error, _variables, context) => {
      completeVersionedOptimisticUpdate(context);
      return refresh();
    },
  });
  const unlink = useMutation({ mutationFn: unlinkUser, onSuccess: refresh });
  const userRename = useMutation({ mutationFn: renameUser, onSuccess: refresh });
  const groupRename = useMutation({ mutationFn: renameGroup, onSuccess: refresh });
  const password = useSensitiveMutation({ mutationFn: savePassword, onSuccess: refresh });
  const removeUser = useMutation({ mutationFn: deleteUser, onSuccess: refresh });
  const removeGroup = useMutation({ mutationFn: deleteGroupUsers, onSuccess: refresh });
  const clone = useMutation({ mutationFn: cloneUsers, onSuccess: refresh });
  const settingsApply = useMutation({ mutationFn: applySettingsToUsers, onSuccess: refresh });
  const create = useSensitiveMutation({ mutationFn: createUsers, onSuccess: refresh });
  return { dashboard, remoteAccess, downloadAccess, groupSync, groupSettings, link, leader, unlink, userRename, groupRename, password, removeUser, removeGroup, clone, settingsApply, create, refresh };
}

export { useUsers };
