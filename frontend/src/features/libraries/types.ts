export type LibraryEntry = {
  server_id: string;
  server_name?: string;
  server_alias?: string;
  server_icon?: string;
  server_icon_style?: string;
  server_icon_color?: string;
  collection_type?: string;
  library_id?: string;
  id?: string;
  library_name?: string;
};

export type LibraryGroup = {
  group_name: string;
  collection_type: string;
  servers: string[];
  libraries: LibraryEntry[];
};

export type GroupedLibrariesPayload = {
  success: boolean;
  groups: LibraryGroup[];
};

export type ScanJob = {
  job_id: string;
  server_id: string;
  library_ids: string[];
  group_name?: string;
  scan_type?: "content" | "metadata";
  status: string;
  progress?: number;
};

export type LibraryScanActivity = {
  jobCount: number;
  progress: number;
  status: string;
};

export type ActiveScanJobsPayload = {
  success: boolean;
  jobs: ScanJob[];
  count: number;
};

export type LibraryScanResponse = {
  success: boolean;
  queued?: boolean;
  queue_position?: number;
  job_id?: string;
  job_ids?: string[];
  message?: string;
};

export type LibraryWorkflowContext = {
  group_name?: string;
  scan_type?: "content" | "metadata";
  server_id?: string;
  library_id?: string;
  libraries?: Array<{ server_id: string; library_id: string }>;
};

export type LibraryAssociation = {
  server_id: string;
  library_id: string;
  group_name: string;
};

export type LibraryGroupOrder = {
  collection_type: string;
  group_name: string;
  position: number;
};

export type LibraryAssociationsPayload = {
  success: boolean;
  associations: LibraryAssociation[];
};

export type LibraryActionTarget = {
  id: string;
  name: string;
  url?: string;
  icon?: string;
  icon_style?: string;
  icon_color?: string;
};

export type LibraryMaintenanceAction = "refresh_libraries" | "refresh_metadata";

export type LibraryActionTargetsPayload = {
  success: boolean;
  actions: Array<{ id: LibraryMaintenanceAction; label: string }>;
  servers: LibraryActionTarget[];
};

export type LibraryActionResponse = {
  success: boolean;
  partial?: boolean;
  message: string;
  results: Array<{
    server_id: string;
    server_name: string;
    success: boolean;
    message: string;
  }>;
};

export type ActiveLibraryScan = {
  server_id: string;
  server_name?: string;
  task_name: string;
  progress?: number;
  task_id?: string;
};

export type ActiveLibraryScansPayload = {
  success: boolean;
  active_scans: ActiveLibraryScan[];
};

export type LibraryScanHistoryJob = {
  id: string;
  group_name?: string;
  scan_type?: "content" | "metadata";
  status: string;
  server_id?: string;
  completed_at?: string;
  updated_at?: string;
  started_at?: string;
  total_libraries?: number;
  progress?: number;
  message?: string;
};

export type LibraryScanHistoryPayload = {
  success: boolean;
  jobs: LibraryScanHistoryJob[];
};

export type LibraryFilters = {
  search: string;
  type: "all" | "movies" | "tvshows" | "other";
};
