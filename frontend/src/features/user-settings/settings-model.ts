import type { UserSettings } from "@/features/user-settings/types";

export function normalizeUserSettings(settings: Partial<UserSettings> | undefined): UserSettings {
  return {
    policy: { ...(settings?.policy || {}) },
    config: { ...(settings?.config || {}) },
    display_preferences: { ...(settings?.display_preferences || {}) },
    libraries: { mode: settings?.libraries?.mode || "all", items: [...(settings?.libraries?.items || [])], groups: { ...(settings?.libraries?.groups || {}) } },
  };
}

export function updateSettingsValue(settings: UserSettings, scope: "policy" | "config" | "display_preferences", key: string, value: unknown): UserSettings {
  return { ...settings, [scope]: { ...settings[scope], [key]: value } };
}

export function mergeUserSettings(current: UserSettings, update: Partial<UserSettings>, applyLibraries = false): UserSettings {
  return {
    policy: { ...current.policy, ...(update.policy || {}) },
    config: { ...current.config, ...(update.config || {}) },
    display_preferences: { ...current.display_preferences, ...(update.display_preferences || {}) },
    libraries: applyLibraries ? { ...current.libraries, ...(update.libraries || {}), items: [...(update.libraries?.items || [])] } : current.libraries,
  };
}

export function userSettingsMatch(
  first: UserSettings,
  second: UserSettings,
): boolean {
  return valuesMatch(first, second);
}

function valuesMatch(first: unknown, second: unknown): boolean {
  if (Object.is(first, second)) return true;
  if (!first || !second || typeof first !== "object" || typeof second !== "object") {
    return false;
  }
  if (Array.isArray(first) || Array.isArray(second)) {
    return (
      Array.isArray(first) &&
      Array.isArray(second) &&
      first.length === second.length &&
      first.every((item, index) => valuesMatch(item, second[index]))
    );
  }

  const firstRecord = first as Record<string, unknown>;
  const secondRecord = second as Record<string, unknown>;
  const firstKeys = Object.keys(firstRecord).sort();
  const secondKeys = Object.keys(secondRecord).sort();
  return (
    firstKeys.length === secondKeys.length &&
    firstKeys.every(
      (key, index) =>
        key === secondKeys[index] &&
        valuesMatch(firstRecord[key], secondRecord[key]),
    )
  );
}

export function parseStructuredValue(value: string, fallback: unknown): unknown {
  if (!value.trim()) return [];
  try { return JSON.parse(value); } catch { return fallback; }
}
