import { request } from "@/lib/http";

type EmbyActionServerResult = {
  server_id: string;
  server_name: string;
  success: boolean;
  message: string;
};

type EmbyActionResult = {
  success: boolean;
  partial?: boolean;
  message: string;
  results: EmbyActionServerResult[];
};

type EmbyTaskStopResult = {
  success: boolean;
  message?: string;
};

function restartEmbyServers(serverId?: string): Promise<EmbyActionResult> {
  return request<EmbyActionResult>("/api/v1/emby/actions", {
    method: "POST",
    body: JSON.stringify({ action: "restart_server", ...(serverId ? { server_id: serverId } : {}) }),
  });
}

function stopEmbyTask(serverId: string, taskId: string): Promise<EmbyTaskStopResult> {
  return request<EmbyTaskStopResult>("/api/v1/emby/stop-task", {
    method: "POST",
    body: JSON.stringify({ server_id: serverId, task_id: taskId }),
  });
}

export { restartEmbyServers, stopEmbyTask };
export type { EmbyActionResult, EmbyActionServerResult, EmbyTaskStopResult };
