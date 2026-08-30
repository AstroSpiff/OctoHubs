import type { SettingsInfo, SettingsTarget } from "@/features/user-settings/types";

type SettingsEditorStatus = {
  label: string;
  tone: "muted" | "success" | "warning";
};

function settingsEditorStatus(
  target: SettingsTarget,
  info: Pick<SettingsInfo, "saved">,
): SettingsEditorStatus {
  if (!info.saved) return { label: "Impostazioni non salvate", tone: "muted" };
  if (target.scope === "user" && target.mismatch) {
    return { label: "Impostazioni salvate, non allineate al gruppo", tone: "warning" };
  }
  if (target.scope === "group" && (target.mismatchCount || 0) > 0) {
    return {
      label: `Impostazioni salvate, ${target.mismatchCount} ${target.mismatchCount === 1 ? "utente non allineato" : "utenti non allineati"}`,
      tone: "warning",
    };
  }
  return { label: "Impostazioni salvate", tone: "success" };
}

function formatSettingsUpdatedAt(value?: string | null): string | null {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("it-IT", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}

export { formatSettingsUpdatedAt, settingsEditorStatus };
export type { SettingsEditorStatus };
