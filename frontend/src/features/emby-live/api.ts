import { request } from "@/lib/http";

import type { EmbyLiveServer, EmbyLiveSnapshot } from "@/features/emby-live/types";

type EmbyServerStatusSnapshot = Pick<
  EmbyLiveServer,
  "status" | "running_tasks" | "tasks_error" | "streams" | "streams_error"
>;

function getEmbyServerStatus(serverId: string): Promise<EmbyServerStatusSnapshot> {
  return request<EmbyServerStatusSnapshot>(
    `/api/v1/emby/server-status/${encodeURIComponent(serverId)}`,
  );
}

function getEmbyLiveSnapshot(signal?: AbortSignal): Promise<EmbyLiveSnapshot> {
  return request<EmbyLiveSnapshot>("/api/v1/emby/status", { signal });
}

export { getEmbyLiveSnapshot, getEmbyServerStatus };
