import type {
  ProbeComboTask,
  ProbeScope,
  ProbeWorkerStatus,
} from "@/features/probe/types";

type ProbeComboServerStatusLike = {
  serverId: string;
  serverName: string;
  status?: Pick<ProbeWorkerStatus, "queue">;
};

/**
 * The recent-items worker can begin before it has published its queue. Keep the
 * workflow board useful during that short interval, as the legacy view did.
 */
export function comboTasksForServers(
  scope: ProbeScope,
  serverStatuses: ProbeComboServerStatusLike[],
): ProbeComboTask[] {
  const reported = uniqueComboTasks(
    serverStatuses.flatMap(({ status }) => status?.queue || []),
  );

  if (reported.length || scope !== "recent") return reported;

  return serverStatuses.flatMap(({ serverId, serverName }) => [
    {
      id: `recent:discovery:${serverId}`,
      type: "discovery",
      server_id: serverId,
      server_name: serverName,
    },
    {
      id: `recent:processing:${serverId}`,
      type: "processing",
      server_id: serverId,
      server_name: serverName,
    },
  ]);
}

function uniqueComboTasks(tasks: ProbeComboTask[]): ProbeComboTask[] {
  const byId = new Map<string, ProbeComboTask>();

  tasks.forEach((task, index) => {
    const key =
      task.id ||
      `${task.server_id || "server"}:${task.type || "task"}:${task.library_id || index}`;
    if (!byId.has(key)) byId.set(key, task);
  });

  return [...byId.values()];
}
