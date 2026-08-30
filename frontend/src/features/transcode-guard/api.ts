import { request } from "@/lib/http";
import type { GuardActionResult, TranscodeGuardStatus } from "@/features/transcode-guard/types";

export function getTranscodeGuardStatus(): Promise<TranscodeGuardStatus> {
  return request<TranscodeGuardStatus>("/api/v1/emby/transcode-guard/status");
}

export function checkTranscodeGuard(): Promise<GuardActionResult> {
  return request<GuardActionResult>("/api/v1/emby/transcode-guard/check-now", { method: "POST" });
}

export function setTranscodeGuardState(action: "start" | "stop"): Promise<GuardActionResult> {
  return request<GuardActionResult>(`/api/v1/emby/transcode-guard/${action}`, { method: "POST" });
}

export function cleanupGuardEvents(before?: string): Promise<{ ok: boolean; deleted: number }> {
  return request<{ ok: boolean; deleted: number }>("/api/v1/emby/transcode-guard/events/cleanup", {
    method: "POST",
    body: JSON.stringify(before ? { before } : {}),
  });
}

export function cleanupGuardStreams(before?: string): Promise<{ ok: boolean; deleted: number }> {
  return request<{ ok: boolean; deleted: number }>("/api/v1/emby/transcode-guard/streams/cleanup", {
    method: "POST",
    body: JSON.stringify(before ? { before } : {}),
  });
}
