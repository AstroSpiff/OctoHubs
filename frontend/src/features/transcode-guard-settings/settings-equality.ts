import type { TranscodeGuardSettings } from "@/features/transcode-guard-settings/types";

function transcodeGuardSettingsEqual(left: TranscodeGuardSettings, right: TranscodeGuardSettings): boolean {
  return jsonValueEqual(left, right);
}

function jsonValueEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left)
      && Array.isArray(right)
      && left.length === right.length
      && left.every((value, index) => jsonValueEqual(value, right[index]));
  }
  if (!isRecord(left) || !isRecord(right)) return false;

  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key) => Object.hasOwn(right, key) && jsonValueEqual(left[key], right[key]));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

export { transcodeGuardSettingsEqual };
