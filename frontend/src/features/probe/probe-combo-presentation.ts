import type {
  ProbeComboTask,
  ProbeScope,
  ProbeWorkerStatus,
} from "@/features/probe/types";

type ProbeComboServerStatusLike = {
  serverId: string;
  serverName: string;
  libraryNames?: Record<string, string>;
  status?: ProbeWorkerStatus;
  discoveryStatus?: ProbeWorkerStatus;
  processingStatus?: ProbeWorkerStatus;
};

type ProbeComboColumn = "todo" | "running" | "terminal";
type ProbeComboOutcome =
  | "completed"
  | "interrupted"
  | "error"
  | "partial"
  | "skipped";

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
  const standalone = standaloneTasksForServers(scope, serverStatuses, reported);
  const available = enrichLibraryNames(
    uniqueComboTasks([...reported, ...standalone]),
    serverStatuses,
  );

  if (scope !== "recent") return available;

  return completeRecentServerTasks(available, serverStatuses);
}

function completeRecentServerTasks(
  tasks: ProbeComboTask[],
  serverStatuses: ProbeComboServerStatusLike[],
): ProbeComboTask[] {
  const taskTypes = recentTaskTypes(tasks, serverStatuses);
  const covered = new Set(
    tasks.flatMap((task) =>
      task.server_id && isRecentTaskType(task.type)
        ? [recentTaskKey(task.server_id, task.type)]
        : []
    ),
  );
  const placeholders = serverStatuses.flatMap(({ serverId, serverName }) =>
    taskTypes.flatMap((type) => {
      const key = recentTaskKey(serverId, type);
      if (covered.has(key)) return [];
      return [{
        id: `recent:${type}:${serverId}`,
        type,
        server_id: serverId,
        server_name: serverName,
      }];
    })
  );

  return [...tasks, ...placeholders];
}

type RecentTaskType = "discovery" | "processing";

function recentTaskTypes(
  tasks: ProbeComboTask[],
  serverStatuses: ProbeComboServerStatusLike[],
): RecentTaskType[] {
  const runningComboModes = serverStatuses.flatMap(({ status }) =>
    status?.running ? [status.board_mode] : []
  );
  if (runningComboModes.includes("combo")) return ["discovery", "processing"];

  const runningTypes = new Set<RecentTaskType>();
  runningComboModes.forEach((mode) => {
    if (isRecentTaskType(mode)) runningTypes.add(mode);
  });
  serverStatuses.forEach(({ discoveryStatus, processingStatus }) => {
    if (discoveryStatus?.running) runningTypes.add("discovery");
    if (processingStatus?.running) runningTypes.add("processing");
  });
  if (runningTypes.size) return orderedRecentTaskTypes(runningTypes);

  const reportedTypes = new Set<RecentTaskType>();
  tasks.forEach((task) => {
    if (isRecentTaskType(task.type)) reportedTypes.add(task.type);
  });
  return reportedTypes.size
    ? orderedRecentTaskTypes(reportedTypes)
    : ["discovery", "processing"];
}

function isRecentTaskType(value: unknown): value is RecentTaskType {
  return value === "discovery" || value === "processing";
}

function orderedRecentTaskTypes(
  taskTypes: Set<RecentTaskType>,
): RecentTaskType[] {
  return (["discovery", "processing"] as const).filter((type) =>
    taskTypes.has(type)
  );
}

function recentTaskKey(serverId: string, taskType: RecentTaskType): string {
  return `${serverId}\u0000${taskType}`;
}

function standaloneTasksForServers(
  scope: ProbeScope,
  serverStatuses: ProbeComboServerStatusLike[],
  reported: ProbeComboTask[],
): ProbeComboTask[] {
  const reportedLibraryNames = new Map(
    reported.flatMap((task) =>
      task.library_id && task.library_name
        ? [[
            `${task.server_id || "server"}\u0000${String(task.library_id)}`,
            task.library_name,
          ] as const]
        : [],
    ),
  );

  return serverStatuses.flatMap((server) => {
    if (server.status?.running) return [];
    return ([
      ["discovery", server.discoveryStatus],
      ["processing", server.processingStatus],
    ] as const).flatMap(([type, phaseStatus]) => {
      if (!phaseStatus || !hasWorkerRun(phaseStatus)) return [];
      const libraryIds = scope === "libraries"
        ? phaseLibraryIds(phaseStatus)
        : [];
      if (libraryIds.length) {
        return libraryIds.map((libraryId) => ({
          id: `${scope}:${type}:${server.serverId}:${libraryId}`,
          type,
          server_id: server.serverId,
          server_name: server.serverName,
          library_id: libraryId,
          library_name:
            server.libraryNames?.[libraryId] ||
            reportedLibraryNames.get(`${server.serverId}\u0000${libraryId}`) ||
            currentLibraryName(phaseStatus, libraryId),
        }));
      }
      return [{
        id: `${scope}:${type}:${server.serverId}`,
        type,
        server_id: server.serverId,
        server_name: server.serverName,
      }];
    });
  });
}

function phaseLibraryIds(status: ProbeWorkerStatus): string[] {
  const targetIds = (status.target_library_ids || []).map(String).filter(Boolean);
  if (targetIds.length) return [...new Set(targetIds)];
  const currentId = String(status.current_library_id || "");
  return currentId ? [currentId] : [];
}

function currentLibraryName(
  status: ProbeWorkerStatus,
  libraryId: string,
): string | undefined {
  return String(status.current_library_id || "") === libraryId
    ? status.current_library_name || undefined
    : undefined;
}

function enrichLibraryNames(
  tasks: ProbeComboTask[],
  statuses: ProbeComboServerStatusLike[],
): ProbeComboTask[] {
  return tasks.map((task) => {
    const libraryId = String(task.library_id || "");
    if (!libraryId || task.library_name) return task;
    const server = statuses.find((entry) => entry.serverId === task.server_id);
    const phaseStatus = task.type === "processing"
      ? server?.processingStatus
      : server?.discoveryStatus;
    const libraryName =
      server?.libraryNames?.[libraryId] ||
      (phaseStatus ? currentLibraryName(phaseStatus, libraryId) : undefined);
    return libraryName ? { ...task, library_name: libraryName } : task;
  });
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

export function comboTaskState(
  task: ProbeComboTask,
  statuses: ProbeComboServerStatusLike[],
): ProbeComboColumn {
  const server = statuses.find((entry) => entry.serverId === task.server_id);
  const comboStatus = server?.status;
  const phaseStatus = task.type === "processing"
    ? server?.processingStatus
    : server?.discoveryStatus;

  if (comboStatus?.running) {
    if (comboStatus.phase === "processing" && task.type === "discovery") {
      return "terminal";
    }
    if (comboStatus.phase !== task.type) return "todo";
    return activePhaseTaskState(
      task,
      phaseStatus || {
        running: true,
        target_library_ids: comboStatus.board_library_ids,
      },
    );
  }

  if (isRecentTask(task)) {
    const currentRunId = latestStandaloneRunId(task.type, statuses);
    if (currentRunId && phaseStatus?.run_id !== currentRunId) return "todo";
  }

  const standaloneState = standalonePhaseTaskState(task, phaseStatus);
  if (standaloneState) return standaloneState;
  if (comboStatus?.board_reset) return "terminal";
  return "todo";
}

function isRecentTask(task: ProbeComboTask): boolean {
  return String(task.id || "").startsWith("recent:") &&
    isRecentTaskType(task.type);
}

function latestStandaloneRunId(
  taskType: ProbeComboTask["type"],
  statuses: ProbeComboServerStatusLike[],
): string | undefined {
  const candidates = statuses.flatMap((server) => {
    const status = taskType === "processing"
      ? server.processingStatus
      : server.discoveryStatus;
    const runId = String(status?.run_id || "");
    const startedAt = Date.parse(String(status?.started_at || ""));
    return runId && Number.isFinite(startedAt) ? [{ runId, startedAt }] : [];
  });
  return candidates.reduce<{ runId: string; startedAt: number } | undefined>(
    (latest, candidate) =>
      !latest || candidate.startedAt > latest.startedAt ? candidate : latest,
    undefined,
  )?.runId;
}

export function comboTaskOutcome(
  task: ProbeComboTask,
  statuses: ProbeComboServerStatusLike[],
): ProbeComboOutcome | undefined {
  const server = statuses.find((entry) => entry.serverId === task.server_id);
  const comboStatus = server?.status;
  const phaseStatus = task.type === "processing"
    ? server?.processingStatus
    : server?.discoveryStatus;
  const recordedTask = comboStatus?.running
    ? undefined
    : comboStatus?.last_run?.tasks?.find((candidate) =>
        sameComboTask(candidate, task)
      );

  if (recordedTask) return recordedTaskOutcome(recordedTask);

  const libraryId = String(task.library_id || "");
  if (libraryId && phaseStatus) {
    if ((phaseStatus.error_library_ids || []).map(String).includes(libraryId)) {
      return "error";
    }
    if (task.type === "processing") {
      const result = phaseStatus.library_queue_results?.[libraryId];
      if (Number(result?.errors || 0) > 0) return "error";
      if (Number(result?.incomplete || 0) > 0) return "partial";
      if (libraryProcessingComplete(phaseStatus, libraryId)) return "completed";
    }
    if ((phaseStatus.completed_library_ids || []).map(String).includes(libraryId)) {
      return "completed";
    }
  }

  const lastLog = String(phaseStatus?.last_log || comboStatus?.last_log || "")
    .toLowerCase();
  if (lastLog.includes("interrott")) {
    return "interrupted";
  }
  if (lastLog.includes("errore") || lastLog.includes("fallit")) return "error";
  if (Number(phaseStatus?.errors || 0) > 0) return "error";
  if (Number(phaseStatus?.incomplete || 0) > 0) return "partial";
  if (!comboStatus?.running) {
    if (comboStatus?.last_run?.status === "interrupted") return "interrupted";
    if (comboStatus?.last_run?.status === "error") return "error";
    if (comboStatus?.last_run?.status === "partial") return "partial";
  }
  return comboTaskState(task, statuses) === "terminal"
    ? "completed"
    : undefined;
}

export function statusForComboTask(
  task: ProbeComboTask,
  statuses: ProbeComboServerStatusLike[],
): ProbeWorkerStatus | undefined {
  const server = statuses.find((entry) => entry.serverId === task.server_id);
  return task.type === "processing"
    ? server?.processingStatus || server?.status
    : server?.discoveryStatus || server?.status;
}

export function progressForComboTask(
  task: ProbeComboTask,
  statuses: ProbeComboServerStatusLike[],
): { completed: number; total: number } | undefined {
  const status = statusForComboTask(task, statuses);
  if (!status) return undefined;
  const libraryId = String(task.library_id || "");

  if (libraryId && task.type === "processing") {
    const total = status.library_queue_totals?.[libraryId];
    if (total === undefined) return undefined;
    const result = status.library_queue_results?.[libraryId];
    const completed = Number(result?.processed || 0)
      + Number(result?.incomplete || 0)
      + Number(result?.errors || 0);
    return { completed: Math.min(completed, total), total };
  }

  if (libraryId && task.type === "discovery") {
    const total = status.library_totals?.[libraryId];
    if (total === undefined) return undefined;
    return {
      completed: Math.min(Number(status.library_scanned?.[libraryId] || 0), total),
      total,
    };
  }

  const total = Number(status.total || 0);
  if (!total) return undefined;
  const completed = Number(status.processed || 0)
    + Number(status.incomplete || 0)
    + Number(status.errors || 0);
  return { completed: Math.min(completed, total), total };
}

export function currentItemForComboTask(
  task: ProbeComboTask,
  statuses: ProbeComboServerStatusLike[],
): string | undefined {
  const status = statusForComboTask(task, statuses);
  if (!status?.current_item) return undefined;
  const libraryId = String(task.library_id || "");
  if (
    libraryId &&
    String(status.current_library_id || "") !== libraryId
  ) {
    return undefined;
  }
  return status.current_item;
}

export function currentLibraryForComboTask(
  task: ProbeComboTask,
  statuses: ProbeComboServerStatusLike[],
): string | undefined {
  if (task.library_name) return task.library_name;
  const status = statusForComboTask(task, statuses);
  return status?.current_library_name || undefined;
}

export function discoveryMetricsForComboTask(
  task: ProbeComboTask,
  statuses: ProbeComboServerStatusLike[],
): { scanned: number; found: number } | undefined {
  if (task.type !== "discovery" || task.library_id) return undefined;
  const status = statusForComboTask(task, statuses);
  if (!status || (!status.started_at && status.total_scanned === undefined)) {
    return undefined;
  }
  return {
    scanned: Number(status.total_scanned || 0),
    found: Number(status.found || 0),
  };
}

function standalonePhaseTaskState(
  task: ProbeComboTask,
  phaseStatus?: ProbeWorkerStatus,
): ProbeComboColumn | undefined {
  if (!phaseStatus) return undefined;
  if (phaseStatus.running) return activePhaseTaskState(task, phaseStatus);
  return hasWorkerRun(phaseStatus) ? "terminal" : undefined;
}

function activePhaseTaskState(
  task: ProbeComboTask,
  phaseStatus?: ProbeWorkerStatus,
): ProbeComboColumn {
  if (!phaseStatus) return "running";
  const libraryId = task.library_id ? String(task.library_id) : "";
  if (!libraryId) return "running";

  const completed = new Set([
    ...(phaseStatus.completed_library_ids || []),
    ...(phaseStatus.error_library_ids || []),
  ].map(String));
  if (completed.has(libraryId) || libraryProcessingComplete(phaseStatus, libraryId)) {
    return "terminal";
  }

  const currentLibraryId = String(phaseStatus.current_library_id || "");
  if (currentLibraryId === libraryId) return "running";
  if (!currentLibraryId) {
    const firstPending = (phaseStatus.target_library_ids || [])
      .map(String)
      .find((candidate) => !completed.has(candidate));
    return firstPending === libraryId ? "running" : "todo";
  }
  return "todo";
}

function libraryProcessingComplete(
  status: ProbeWorkerStatus,
  libraryId: string,
): boolean {
  const total = status.library_queue_totals?.[libraryId];
  const result = status.library_queue_results?.[libraryId];
  if (total === undefined || !result) return false;
  return Number(result.processed || 0)
    + Number(result.incomplete || 0)
    + Number(result.errors || 0) >= Number(total);
}

function hasWorkerRun(status: ProbeWorkerStatus): boolean {
  return Boolean(status.started_at || status.last_log);
}

function sameComboTask(left: ProbeComboTask, right: ProbeComboTask): boolean {
  if (left.id && right.id) return left.id === right.id;
  return left.type === right.type
    && String(left.server_id || "") === String(right.server_id || "")
    && String(left.library_id || "") === String(right.library_id || "");
}

function recordedTaskOutcome(task: ProbeComboTask): ProbeComboOutcome {
  const note = String(task.note || "").toLowerCase();
  if (task.result === "error") return "error";
  if (task.result === "skipped") return "skipped";
  if (task.result === "success") return "completed";
  if (note.includes("interrott")) {
    return "interrupted";
  }
  if (task.result === "warning") return "partial";
  return "completed";
}

export type {
  ProbeComboColumn,
  ProbeComboOutcome,
  ProbeComboServerStatusLike,
};
