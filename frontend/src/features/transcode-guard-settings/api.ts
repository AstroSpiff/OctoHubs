import { request } from "@/lib/http";
import type { GuardSettingsResponse, GuardSettingsSaveResult, TranscodeGuardSettings } from "@/features/transcode-guard-settings/types";

export function getTranscodeGuardSettings(): Promise<GuardSettingsResponse> {
  return request<GuardSettingsResponse>("/api/v1/emby/transcode-guard/settings");
}

export function saveTranscodeGuardSettings(settings: TranscodeGuardSettings): Promise<GuardSettingsSaveResult> {
  return request<GuardSettingsSaveResult>("/api/v1/emby/transcode-guard/settings", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}
