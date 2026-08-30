import { request } from "@/lib/http";
import type { SettingsInfo, SettingsPreset, SettingsSchema, SettingsTarget, UserSettings } from "@/features/user-settings/types";

export function getSettingsSchema(): Promise<SettingsSchema> {
  return request<SettingsSchema>("/api/v1/emby/users/settings-schema");
}

export function getSettingsInfo(target: SettingsTarget): Promise<SettingsInfo> {
  const params = new URLSearchParams(target.scope === "group" ? { group_id: target.groupId } : { server_id: target.serverId, user_id: target.userId });
  return request<SettingsInfo>(`/api/v1/emby/users/settings?${params.toString()}`);
}

export function saveSettings({ target, settings }: { target: SettingsTarget; settings: UserSettings }): Promise<{ ok: boolean }> {
  const endpoint = target.scope === "group" ? "/api/v1/emby/users/settings-group" : "/api/v1/emby/users/settings";
  const body = target.scope === "group" ? { group_id: target.groupId, settings } : { server_id: target.serverId, user_id: target.userId, settings };
  return request<{ ok: boolean }>(endpoint, { method: "POST", body: JSON.stringify(body) });
}

export function getSettingsPresets(): Promise<{ ok: boolean; presets: SettingsPreset[] }> {
  return request<{ ok: boolean; presets: SettingsPreset[] }>("/api/v1/emby/users/settings-presets");
}

export function getSettingsPreset(presetId: string): Promise<{ ok: boolean; preset: SettingsPreset }> {
  return request<{ ok: boolean; preset: SettingsPreset }>(`/api/v1/emby/users/settings-presets/${encodeURIComponent(presetId)}`);
}

export function saveSettingsPreset({ id, label, settings, applyLibraries }: { id?: string; label: string; settings: UserSettings; applyLibraries: boolean }): Promise<{ ok: boolean; preset: SettingsPreset }> {
  return request<{ ok: boolean; preset: SettingsPreset }>("/api/v1/emby/users/settings-presets", { method: "POST", body: JSON.stringify({ id, label, settings, apply_libraries: applyLibraries }) });
}

export function duplicateSettingsPreset({ presetId, label }: { presetId: string; label: string }): Promise<{ ok: boolean; preset: SettingsPreset }> {
  return request<{ ok: boolean; preset: SettingsPreset }>(`/api/v1/emby/users/settings-presets/${encodeURIComponent(presetId)}/duplicate`, { method: "POST", body: JSON.stringify({ label }) });
}

export function deleteSettingsPreset(presetId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/emby/users/settings-presets/${encodeURIComponent(presetId)}/delete`, { method: "POST" });
}
