import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { useMemo } from "react";

import { deleteProbeBlacklist, deleteProbeHistory, deleteProbeQueue, getProbeBlacklist, getProbeConfig, getProbeHistory, getProbeLibraries, getProbeQueue, retryBlacklistedProbeItem, retryProbeItem, runProbeAction, saveProbeConfig } from "@/features/probe/api";
import type { ProbeDataTab } from "@/features/probe/probe-data-tab-options";
import type { ProbeBlacklistItem, ProbeConfig, ProbeHistoryItem, ProbeQueueItem, ProbeScope } from "@/features/probe/types";

type ProbePagedItem = {
  id?: number;
  item_id: string;
  media_source_id?: string;
  server_id?: string;
};
type CursorMap = Record<string, number | null>;
type CombinedPage<Item> = { items: Item[]; nextCursors: CursorMap };
type PageLoader<Item> = (
  serverId: string,
  cursor: number,
  signal: AbortSignal,
) => Promise<{ items: Item[]; nextCursor: number | null }>;

function useProbeLibraries() {
  return useQuery({ queryKey: ["probe-libraries"], queryFn: getProbeLibraries, staleTime: 30_000 });
}

function useProbeConfig(serverId: string | null) {
  return useQuery({ queryKey: ["probe-config", serverId], queryFn: () => getProbeConfig(serverId || ""), enabled: Boolean(serverId) });
}

function useProbePagedDataset<Item extends ProbePagedItem>({
  active,
  interval,
  queryKey,
  serverIds,
  loadPage,
}: {
  active: boolean;
  interval: number;
  queryKey: readonly string[];
  serverIds: string[];
  loadPage: PageLoader<Item>;
}) {
  const initialCursors = useMemo<CursorMap>(
    () => Object.fromEntries(serverIds.map((serverId) => [serverId, 0])),
    [serverIds],
  );
  const query = useInfiniteQuery({
    queryKey,
    initialPageParam: initialCursors,
    enabled: active && serverIds.length > 0,
    queryFn: async ({ pageParam, signal }) => {
      const cursors = pageParam as CursorMap;
      const activeServerIds = serverIds.filter(
        (serverId) => cursors[serverId] != null,
      );
      const pages = await Promise.all(
        activeServerIds.map((serverId) =>
          loadPage(serverId, cursors[serverId] as number, signal),
        ),
      );
      return {
        items: pages.flatMap((page) => page.items),
        nextCursors: Object.fromEntries(
          serverIds.map((serverId) => {
            const pageIndex = activeServerIds.indexOf(serverId);
            return [
              serverId,
              pageIndex >= 0 ? pages[pageIndex].nextCursor : null,
            ];
          }),
        ),
      } satisfies CombinedPage<Item>;
    },
    getNextPageParam: (lastPage) =>
      Object.values(lastPage.nextCursors).some((cursor) => cursor != null)
        ? lastPage.nextCursors
        : undefined,
    refetchInterval: (currentQuery) => {
      const data = currentQuery.state.data as
        | InfiniteData<CombinedPage<Item>, CursorMap>
        | undefined;
      return (data?.pages.length || 0) <= 1 ? interval : false;
    },
  });
  const data = useMemo(() => {
    const unique = new Map<string, Item>();
    query.data?.pages.forEach((page) => {
      page.items.forEach((item) => {
        const key = [
          item.server_id || "",
          item.id ?? "",
          item.item_id,
          item.media_source_id || "",
        ].join(":");
        unique.set(key, item);
      });
    });
    return [...unique.values()];
  }, [query.data]);

  return { ...query, data, queryKey };
}

function useProbeScopeData(
  scope: ProbeScope,
  serverIds: string[],
  activeTab: ProbeDataTab = "queue",
) {
  const client = useQueryClient();
  const key = [scope, serverIds.join(",")];
  const queue = useProbePagedDataset<ProbeQueueItem>({
    active: activeTab === "queue",
    interval: 5_000,
    queryKey: ["probe-queue", ...key],
    serverIds,
    loadPage: async (serverId, cursor, signal) => {
      const page = await getProbeQueue(serverId, scope, cursor, signal);
      return {
        items: page.queue.map((item) => ({ ...item, server_id: item.server_id || serverId })),
        nextCursor: page.has_more ? validNextCursor(page.next_cursor, cursor) : null,
      };
    },
  });
  const history = useProbePagedDataset<ProbeHistoryItem>({
    active: activeTab === "history",
    interval: 10_000,
    queryKey: ["probe-history", ...key],
    serverIds,
    loadPage: async (serverId, cursor, signal) => {
      const page = await getProbeHistory(serverId, scope, cursor, signal);
      return {
        items: page.history.map((item) => ({ ...item, server_id: item.server_id || serverId })),
        nextCursor: page.has_more ? validNextCursor(page.next_cursor, cursor) : null,
      };
    },
  });
  const errors = useProbePagedDataset<ProbeBlacklistItem>({
    active: activeTab === "errors",
    interval: 10_000,
    queryKey: ["probe-blacklist-error", ...key],
    serverIds,
    loadPage: async (serverId, cursor, signal) => {
      const page = await getProbeBlacklist(serverId, scope, "error", cursor, signal);
      return {
        items: page.blacklist.map((item) => ({ ...item, server_id: item.server_id || serverId })),
        nextCursor: page.has_more ? validNextCursor(page.next_cursor, cursor) : null,
      };
    },
  });
  const incomplete = useProbePagedDataset<ProbeBlacklistItem>({
    active: activeTab === "incomplete",
    interval: 10_000,
    queryKey: ["probe-blacklist-incomplete", ...key],
    serverIds,
    loadPage: async (serverId, cursor, signal) => {
      const page = await getProbeBlacklist(serverId, scope, "incomplete", cursor, signal);
      return {
        items: page.blacklist.map((item) => ({ ...item, server_id: item.server_id || serverId })),
        nextCursor: page.has_more ? validNextCursor(page.next_cursor, cursor) : null,
      };
    },
  });
  const pagedQueries = [queue, history, errors, incomplete];
  const refresh = () => Promise.all(
    pagedQueries.map((query) => client.resetQueries({ queryKey: query.queryKey, exact: true })),
  );
  const action = useMutation({ mutationFn: ({ path, body }: { path: string; body?: Record<string, unknown> }) => runProbeAction(path, body), onSuccess: refresh });
  const removeQueue = useMutation({ mutationFn: deleteProbeQueue, onSuccess: refresh });
  const clearHistory = useMutation({ mutationFn: deleteProbeHistory, onSuccess: refresh });
  const removeBlacklist = useMutation({ mutationFn: deleteProbeBlacklist, onSuccess: refresh });
  const retry = useMutation({ mutationFn: retryProbeItem, onSuccess: refresh });
  const retryBlacklisted = useMutation({ mutationFn: retryBlacklistedProbeItem, onSuccess: refresh });
  const saveConfig = useMutation({ mutationFn: ({ serverId, config }: { serverId: string; config: ProbeConfig }) => saveProbeConfig(serverId, config), onSuccess: (result, variables) => { client.setQueryData(["probe-config", variables.serverId], result); } });
  return { queue, history, errors, incomplete, action, removeQueue, clearHistory, removeBlacklist, retry, retryBlacklisted, saveConfig, refresh };
}

function validNextCursor(value: number | null | undefined, current: number) {
  if (!Number.isInteger(value) || value == null || value < 1 || value === current) {
    throw new Error("Paginazione Probe non valida.");
  }
  return value;
}

export { useProbeConfig, useProbeLibraries, useProbeScopeData };
