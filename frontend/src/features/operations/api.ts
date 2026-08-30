import { request } from "@/lib/http";
import type { ClearCompletedResult, OperationsSnapshot } from "@/features/operations/types";

export function getOperations(): Promise<OperationsSnapshot> {
  return request<OperationsSnapshot>("/api/v1/operations");
}

export function clearCompletedOperations(): Promise<ClearCompletedResult> {
  return request<ClearCompletedResult>("/api/v1/operations/clear-completed", { method: "POST" });
}

export function stopWorkflow(): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>("/api/v1/workflow/stop", { method: "POST" });
}
