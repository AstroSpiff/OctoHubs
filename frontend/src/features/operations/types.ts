export type OperationStatus = "queued" | "running" | "success" | "error" | "skipped" | "interrupted";

export type OperationWorkflowStep = {
  id?: string;
  label?: string;
  status?: string;
  details?: string;
  progress?: number;
};

export type OperationDetails = Record<string, unknown> & {
  can_stop?: boolean;
  current_step_label?: string;
  workflow_steps?: OperationWorkflowStep[];
};

export type Operation = {
  id: string;
  kind: string;
  title: string;
  summary: string;
  status: OperationStatus;
  message: string;
  progress: number;
  current: number;
  total: number | null;
  details: OperationDetails;
  result?: Record<string, unknown> | null;
  error: string | null;
  started_at: string;
  updated_at: string;
  finished_at: string | null;
};

export type OperationsSnapshot = {
  ok: boolean;
  operations: Operation[];
  active_count: number;
};

export type ClearCompletedResult = { ok: boolean; removed: number };
