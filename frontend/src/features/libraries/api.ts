import { request } from "@/lib/http";
import type {
  ActiveLibraryScansPayload,
  ActiveScanJobsPayload,
  GroupedLibrariesPayload,
  LibraryActionResponse,
  LibraryActionTargetsPayload,
  LibraryAssociation,
  LibraryAssociationsPayload,
  LibraryEntry,
  LibraryGroup,
  LibraryGroupOrder,
  LibraryMaintenanceAction,
  LibraryScanHistoryPayload,
  LibraryScanResponse,
  LibraryWorkflowContext,
} from "@/features/libraries/types";

export function getGroupedLibraries(): Promise<GroupedLibrariesPayload> {
  return request<GroupedLibrariesPayload>("/api/v1/emby/grouped-libraries");
}

export function getActiveScanJobs(): Promise<ActiveScanJobsPayload> {
  return request<ActiveScanJobsPayload>("/api/v1/emby/active-scan-jobs");
}

export function scanLibraryGroup(
  group: LibraryGroup,
  scanType: "content" | "metadata",
): Promise<LibraryScanResponse> {
  return request<LibraryScanResponse>("/api/v1/emby/scan-group-tracked", {
    method: "POST",
    body: JSON.stringify({
      group_name: group.group_name,
      scan_type: scanType,
      libraries: group.libraries.map((library) => ({
        server_id: library.server_id,
        library_id: library.library_id || library.id,
      })),
    }),
  });
}

export function scanSingleLibrary(
  library: LibraryEntry,
  scanType: "content" | "metadata",
): Promise<LibraryScanResponse> {
  const libraryId = library.library_id || library.id;
  if (!libraryId)
    return Promise.reject(
      new Error("Identificativo libreria non disponibile."),
    );
  return request<LibraryScanResponse>("/api/v1/emby/scan-library-tracked", {
    method: "POST",
    body: JSON.stringify({
      server_id: library.server_id,
      library_ids: [libraryId],
      scan_type: scanType,
    }),
  });
}

export function getLibraryAssociations(): Promise<LibraryAssociationsPayload> {
  return request<LibraryAssociationsPayload>("/api/v1/emby/associations");
}

export function saveLibraryAssociations(
  associations: LibraryAssociation[],
): Promise<LibraryAssociationsPayload> {
  return request<LibraryAssociationsPayload>("/api/v1/emby/associations", {
    method: "POST",
    body: JSON.stringify(associations),
  });
}

export function saveLibraryGroupOrder(
  order: LibraryGroupOrder[],
): Promise<{ success: boolean }> {
  return request<{ success: boolean }>("/api/v1/emby/group-order", {
    method: "POST",
    body: JSON.stringify(order),
  });
}

export function saveEmbyServerOrder(
  serverIds: string[],
): Promise<{ success: boolean }> {
  return request<{ success: boolean }>("/api/v1/emby/server-order", {
    method: "POST",
    body: JSON.stringify(serverIds),
  });
}

export function getLibraryActionTargets(): Promise<LibraryActionTargetsPayload> {
  return request<LibraryActionTargetsPayload>("/api/v1/emby/actions/targets");
}

export function runLibraryMaintenance(input: {
  action: LibraryMaintenanceAction;
  serverId?: string;
}): Promise<LibraryActionResponse> {
  return request<LibraryActionResponse>("/api/v1/emby/actions", {
    method: "POST",
    body: JSON.stringify({
      action: input.action,
      server_id: input.serverId || "",
    }),
  });
}

export function getActiveLibraryScans(): Promise<ActiveLibraryScansPayload> {
  return request<ActiveLibraryScansPayload>("/api/v1/emby/active-scans");
}

export function getLibraryScanHistory(): Promise<LibraryScanHistoryPayload> {
  return request<LibraryScanHistoryPayload>("/api/v1/emby/scan-jobs/history");
}

export function resetLibraryScanHistory(): Promise<{
  success: boolean;
  message: string;
}> {
  return request<{ success: boolean; message: string }>(
    "/api/v1/emby/scan-jobs/reset",
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function deleteLibraryScanHistoryJob(jobId: string): Promise<{
  success: boolean;
  message: string;
}> {
  return request<{ success: boolean; message: string }>(
    `/api/v1/emby/scan-job/${encodeURIComponent(jobId)}`,
    { method: "DELETE" },
  );
}

export function startLibraryWorkflow(
  context: LibraryWorkflowContext,
): Promise<{ success: boolean; message?: string }> {
  return request<{ success: boolean; message?: string }>(
    "/api/v1/workflow/start",
    {
      method: "POST",
      body: JSON.stringify({ type: "smart", context }),
    },
  );
}
