import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteProbeBlacklist, deleteProbeHistory, deleteProbeQueue, getProbeBlacklist, getProbeConfig, getProbeHistory, getProbeLibraries, getProbeQueue, retryBlacklistedProbeItem, retryProbeItem, runProbeAction, saveProbeConfig } from "@/features/probe/api";
import type { ProbeConfig, ProbeScope } from "@/features/probe/types";

function useProbeLibraries() {
  return useQuery({ queryKey: ["probe-libraries"], queryFn: getProbeLibraries, staleTime: 30_000 });
}

function useProbeConfig(serverId: string | null) {
  return useQuery({ queryKey: ["probe-config", serverId], queryFn: () => getProbeConfig(serverId || ""), enabled: Boolean(serverId) });
}

function useProbeScopeData(scope: ProbeScope, serverIds: string[]) {
  const client = useQueryClient();
  const key = [scope, serverIds.join(",")];
  const queue = useQuery({ queryKey: ["probe-queue", ...key], queryFn: async () => (await Promise.all(serverIds.map(async (serverId) => ({ serverId, data: await getProbeQueue(serverId, scope) })))).flatMap(({ serverId, data }) => data.queue.map((item) => ({ ...item, server_id: item.server_id || serverId }))), enabled: serverIds.length > 0, refetchInterval: 5_000 });
  const history = useQuery({ queryKey: ["probe-history", ...key], queryFn: async () => (await Promise.all(serverIds.map(async (serverId) => ({ serverId, data: await getProbeHistory(serverId, scope) })))).flatMap(({ serverId, data }) => data.history.map((item) => ({ ...item, server_id: item.server_id || serverId }))), enabled: serverIds.length > 0, refetchInterval: 10_000 });
  const errors = useQuery({ queryKey: ["probe-blacklist-error", ...key], queryFn: async () => (await Promise.all(serverIds.map(async (serverId) => ({ serverId, data: await getProbeBlacklist(serverId, scope, "error") })))).flatMap(({ serverId, data }) => data.blacklist.map((item) => ({ ...item, server_id: item.server_id || serverId }))), enabled: serverIds.length > 0, refetchInterval: 10_000 });
  const incomplete = useQuery({ queryKey: ["probe-blacklist-incomplete", ...key], queryFn: async () => (await Promise.all(serverIds.map(async (serverId) => ({ serverId, data: await getProbeBlacklist(serverId, scope, "incomplete") })))).flatMap(({ serverId, data }) => data.blacklist.map((item) => ({ ...item, server_id: item.server_id || serverId }))), enabled: serverIds.length > 0, refetchInterval: 10_000 });
  const refresh = () => Promise.all([queue.refetch(), history.refetch(), errors.refetch(), incomplete.refetch()]);
  const action = useMutation({ mutationFn: ({ path, body }: { path: string; body?: Record<string, unknown> }) => runProbeAction(path, body), onSuccess: refresh });
  const removeQueue = useMutation({ mutationFn: deleteProbeQueue, onSuccess: refresh });
  const clearHistory = useMutation({ mutationFn: deleteProbeHistory, onSuccess: refresh });
  const removeBlacklist = useMutation({ mutationFn: deleteProbeBlacklist, onSuccess: refresh });
  const retry = useMutation({ mutationFn: retryProbeItem, onSuccess: refresh });
  const retryBlacklisted = useMutation({ mutationFn: retryBlacklistedProbeItem, onSuccess: refresh });
  const saveConfig = useMutation({ mutationFn: ({ serverId, config }: { serverId: string; config: ProbeConfig }) => saveProbeConfig(serverId, config), onSuccess: (result, variables) => { client.setQueryData(["probe-config", variables.serverId], result); } });
  return { queue, history, errors, incomplete, action, removeQueue, clearHistory, removeBlacklist, retry, retryBlacklisted, saveConfig, refresh };
}

export { useProbeConfig, useProbeLibraries, useProbeScopeData };
