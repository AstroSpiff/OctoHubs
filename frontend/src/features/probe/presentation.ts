import type { ProbeScope, ProbeWorkerStatus } from "@/features/probe/types";

export const probeConfigDefaults = {
  window_size: 500,
  window_threshold: 0.9,
  max_days: 60,
  max_items: 2000,
  safety_margin_days: 7,
  probe_parallelism: 1,
  media_policy: "strm_only" as const,
};

export function probeScopeLabel(scope: ProbeScope): string {
  return scope === "recent" ? "Ultimi aggiunti" : "Librerie";
}

export function probeStatusLabel(status?: ProbeWorkerStatus): string {
  return status?.running ? "In esecuzione" : "Pronto";
}

export function formatProbeDate(value?: string): string {
  if (!value) return "Non disponibile";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("it-IT", { dateStyle: "short", timeStyle: "medium" }).format(date);
}

export function probeItemLabel(item: { display_name?: string; name?: string; item_name?: string }): string {
  return item.display_name || item.name || item.item_name || "Elemento senza nome";
}

export function probeItemHasIssue(item: { status?: string; error_type?: string; retry_count?: number }): boolean {
  return item.status === "error" || item.status === "incomplete" || Boolean(item.error_type) || Number(item.retry_count || 0) > 0;
}

export function mergeProbeWorkerStatuses(statuses: ProbeWorkerStatus[]): ProbeWorkerStatus | undefined {
  if (!statuses.length) return undefined;

  let runningCount = 0;

  const merged = statuses.reduce<ProbeWorkerStatus>((summary, status) => {
    const running = Boolean(status.running);
    if (running) runningCount += 1;

    return {
      running: Boolean(summary.running || running),
      found: Number(summary.found || 0) + Number(status.found || 0),
      total_scanned:
        Number(summary.total_scanned || 0) + Number(status.total_scanned || 0),
      processed: Number(summary.processed || 0) + Number(status.processed || 0),
      incomplete:
        Number(summary.incomplete || 0) + Number(status.incomplete || 0),
      errors: Number(summary.errors || 0) + Number(status.errors || 0),
      // Some workers publish the same shared queue total to every server.
      // The old UI used the maximum here so the multi-server view stays truthful.
      total: Math.max(Number(summary.total || 0), Number(status.total || 0)),
      phase: running ? status.phase || summary.phase : summary.phase,
      current_item: running
        ? status.current_item || summary.current_item
        : summary.current_item,
      last_log: running ? status.last_log || summary.last_log : summary.last_log,
      queue: [...(summary.queue || []), ...(status.queue || [])],
    };
  }, {});

  if (merged.running && !merged.last_log) {
    merged.last_log = `${runningCount} server in esecuzione`;
  }

  return merged;
}

export function probeProgress(status?: ProbeWorkerStatus): { completed: number; total: number } | undefined {
  const total = Number(status?.total || 0);
  if (!total) return undefined;
  const completed = Number(status?.processed || 0) + Number(status?.incomplete || 0) + Number(status?.errors || 0);
  return { completed: Math.min(completed, total), total };
}
