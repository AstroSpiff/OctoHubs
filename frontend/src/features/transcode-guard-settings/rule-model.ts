import type { GuardMode, GuardRule, PresenceState, StreamState, TranscodeGuardSettings } from "@/features/transcode-guard-settings/types";

export const modeLabels: Record<GuardMode, string> = {
  monitor: "Solo monitoraggio",
  warn: "Avvisa",
  warn_then_stop: "Avvisa e ferma",
  stop: "Ferma subito",
};

const streamStateLabels: Record<StreamState, string> = { any: "qualsiasi", transcode: "transcodifica", direct: "diretto" };
const presenceLabels: Record<PresenceState, string> = { any: "qualsiasi", present: "presente", absent: "assente" };

export function createGuardRule(): GuardRule {
  const id = `rule-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    id, name: "Nuova regola", type: "rule", enabled: false, profile: "video_transcode_threshold", mode: "monitor",
    video_state: "transcode", audio_state: "any", remux_state: "any", transformation_state: "any", min_source_height: 2160,
    correction_window_seconds: 60, message_display_mode: "toast", warning_timeout_ms: 45_000, max_warnings: 3,
    message_cooldown_seconds: 30, allow_audio_only_transcode: true, allow_container_remux: true, ignore_paused: true,
    server_ids: [], excluded_users: [], excluded_clients: [], excluded_devices: [], excluded_ips: [],
    message_header: "OctoHubs Transcode Guard",
    message_text: "{title} è in transcodifica video su {server}. Controlla qualità di riproduzione, versione o client per evitare perdita di qualità.",
    stop_processing: true, children: [],
  };
}

export function duplicateGuardRule(rule: GuardRule): GuardRule {
  return { ...rule, id: createGuardRule().id, name: `${rule.name || "Regola"} copia`, server_ids: [...rule.server_ids], excluded_users: [...rule.excluded_users], excluded_clients: [...rule.excluded_clients], excluded_devices: [...rule.excluded_devices], excluded_ips: [...rule.excluded_ips] };
}

export function listFromInput(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function ruleSummary(rule: GuardRule) {
  const threshold = rule.min_source_height ? ` · ${rule.min_source_height}p+` : "";
  return `Video ${streamStateLabels[rule.video_state]} · Audio ${streamStateLabels[rule.audio_state]} · Remux ${presenceLabels[rule.remux_state]}${threshold}`;
}

export function validationMessage(settings: TranscodeGuardSettings) {
  const invalid = settings.rules.find((rule) => rule.enabled && !rule.server_ids.length);
  return invalid ? `Seleziona almeno un server per “${invalid.name || "Regola"}” o disattivala.` : "";
}

export function messagesEnabled(rule: GuardRule) {
  return rule.mode === "warn" || rule.mode === "warn_then_stop";
}
