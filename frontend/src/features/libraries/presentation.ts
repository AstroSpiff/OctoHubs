import type {
  LibraryEntry,
  LibraryFilters,
  LibraryGroup,
  LibraryGroupOrder,
  LibraryScanActivity,
  LibraryScanHistoryJob,
  ScanJob,
} from "@/features/libraries/types";
import type { Severity } from "@/components/ui/badge";

export const defaultLibraryFilters: LibraryFilters = {
  search: "",
  type: "all",
};

export const hiddenLibraryGroupName = "Nascondi";

export function libraryTypeLabel(type: string): string {
  if (type === "movies") return "Film";
  if (type === "tvshows") return "Serie TV";
  return "Cartelle e altro";
}

export function libraryTypeBucket(type: string): LibraryFilters["type"] {
  if (type === "movies" || type === "tvshows") return type;
  return "other";
}

export function visibleLibraryGroups(
  groups: LibraryGroup[],
  filters: LibraryFilters,
): LibraryGroup[] {
  const search = filters.search.trim().toLocaleLowerCase("it-IT");
  return groups.filter((group) => {
    if (group.group_name === hiddenLibraryGroupName) return false;
    if (
      filters.type !== "all" &&
      libraryTypeBucket(group.collection_type) !== filters.type
    )
      return false;
    if (!search) return true;
    return [
      group.group_name,
      libraryTypeLabel(group.collection_type),
      ...group.libraries.flatMap((library) => [
        library.library_name,
        library.server_alias,
        library.server_name,
      ]),
    ].some((value) => value?.toLocaleLowerCase("it-IT").includes(search));
  });
}

export function libraryOverview(groups: LibraryGroup[]) {
  const visibleGroups = groups.filter(
    (group) => group.group_name !== hiddenLibraryGroupName,
  );
  return {
    groups: visibleGroups.length,
    libraries: visibleGroups.reduce(
      (total, group) => total + group.libraries.length,
      0,
    ),
    servers: new Set(
      visibleGroups.flatMap((group) =>
        group.libraries.map((library) => library.server_id),
      ),
    ).size,
  };
}

export function formatLibraryDate(value?: string): string {
  if (!value) return "Non disponibile";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function formatLibraryDuration(startedAt?: string, completedAt?: string): string {
  if (!startedAt || !completedAt) return "Durata non disponibile";
  const started = new Date(startedAt).getTime();
  const completed = new Date(completedAt).getTime();
  if (Number.isNaN(started) || Number.isNaN(completed) || completed < started) return "Durata non disponibile";

  const seconds = Math.floor((completed - started) / 1_000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  if (hours) return `${hours}h ${minutes % 60}m`;
  if (minutes) return `${minutes}m ${seconds % 60}s`;
  return `${seconds}s`;
}

export function libraryScanTypeLabel(type?: string): string {
  return type === "metadata" ? "Metadata" : "File";
}

export function libraryScanStatusLabel(status?: string): string {
  if (status === "completed") return "Completata";
  if (status === "error") return "Errore";
  if (status === "active") return "In corso";
  if (status === "queued") return "In coda";
  return status || "Non disponibile";
}

export function libraryScanStatusSeverity(status?: string): Severity {
  if (status === "completed") return "ok";
  if (status === "error") return "error";
  if (status === "active") return "info";
  if (status === "queued") return "neutral";
  return "unknown";
}

export function libraryScanProgress(value?: number): number | undefined {
  if (!Number.isFinite(value)) return undefined;
  const normalized = value && value > 1 ? value / 100 : value || 0;
  return Math.round(Math.max(0, Math.min(1, normalized)) * 100);
}

function scanProgressValue(value?: number): number {
  return libraryScanProgress(value) || 0;
}

function scanActivity(jobs: ScanJob[]): LibraryScanActivity | undefined {
  if (!jobs.length) return undefined;
  const active = jobs.some((job) => job.status === "active");
  return {
    jobCount: jobs.length,
    progress: Math.round(
      jobs.reduce((total, job) => total + scanProgressValue(job.progress), 0) /
        jobs.length,
    ),
    status: active ? "active" : "queued",
  };
}

function hasLibrary(job: ScanJob, library: LibraryEntry): boolean {
  const libraryId = library.library_id || library.id;
  return (
    Boolean(libraryId) &&
    job.server_id === library.server_id &&
    job.library_ids.some((id) => String(id) === String(libraryId))
  );
}

export function libraryEntryScanActivity(
  library: LibraryEntry,
  jobs: ScanJob[],
): LibraryScanActivity | undefined {
  return scanActivity(jobs.filter((job) => hasLibrary(job, library)));
}

export function libraryGroupScanActivity(
  group: LibraryGroup,
  jobs: ScanJob[],
): LibraryScanActivity | undefined {
  return scanActivity(
    jobs.filter(
      (job) =>
        job.group_name === group.group_name ||
        group.libraries.some((library) => hasLibrary(job, library)),
    ),
  );
}

export function latestLibraryGroupHistory(
  group: LibraryGroup,
  jobs: LibraryScanHistoryJob[],
): LibraryScanHistoryJob | undefined {
  return jobs
    .filter((job) => job.group_name === group.group_name)
    .reduce<LibraryScanHistoryJob | undefined>((latest, job) => {
      if (!latest) return job;
      const latestTime = Date.parse(
        latest.completed_at || latest.updated_at || latest.started_at || "",
      );
      const jobTime = Date.parse(
        job.completed_at || job.updated_at || job.started_at || "",
      );
      return Number.isNaN(jobTime) ||
        (!Number.isNaN(latestTime) && latestTime >= jobTime)
        ? latest
        : job;
    }, undefined);
}

export function libraryGroupOrder(groups: LibraryGroup[]): LibraryGroupOrder[] {
  const positions = new Map<string, number>();
  return groups.map((group) => {
    const position = positions.get(group.collection_type) || 0;
    positions.set(group.collection_type, position + 1);
    return {
      collection_type: group.collection_type,
      group_name: group.group_name,
      position,
    };
  });
}

export function moveLibraryOrderItem<T>(
  items: T[],
  index: number,
  direction: -1 | 1,
): T[] {
  const nextIndex = index + direction;
  if (index < 0 || nextIndex < 0 || index >= items.length || nextIndex >= items.length)
    return items;
  const copy = [...items];
  [copy[index], copy[nextIndex]] = [copy[nextIndex], copy[index]];
  return copy;
}

export function moveLibraryOrderItemTo<T>(
  items: T[],
  fromIndex: number,
  targetIndex: number,
  after = false,
): T[] {
  if (
    fromIndex < 0 ||
    targetIndex < 0 ||
    fromIndex >= items.length ||
    targetIndex >= items.length ||
    fromIndex === targetIndex
  ) {
    return items;
  }

  const copy = [...items];
  const [item] = copy.splice(fromIndex, 1);
  const targetPosition = targetIndex - (fromIndex < targetIndex ? 1 : 0);
  copy.splice(targetPosition + (after ? 1 : 0), 0, item);
  return copy;
}
