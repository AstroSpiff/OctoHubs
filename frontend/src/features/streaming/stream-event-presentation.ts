type StreamEventRecord = Record<string, unknown>;

const playerActionSources = new Set(["player", "plugin", "proxy"]);

const technicalSignalLabels: Record<string, string> = {
  video_transcode: "Transcodifica video",
  audio_transcode: "Transcodifica audio",
  subtitle_burnin: "Sottotitoli burn-in",
  remux: "Remux",
  browser_playback: "Riproduzione browser",
  unknown_height: "Metadati incompleti",
};

const actionLabels: Record<string, string> = {
  warn: "Avviso inviato",
  warning_error: "Errore invio avviso",
  play: "Riproduzione",
  stop: "Stop del Guard",
  exit: "Uscito",
  unpause: "Ripresa",
  resolved: "Risolto",
  resolved_later: "Risolto successivamente",
  resolution_change: "Cambio risoluzione",
  partial_resolved: "Risolto parzialmente",
  relapse: "Ricaduta",
  detected: "Violazione rilevata",
  pending_exit: "In attesa di uscita",
};

function streamEventKey(value: unknown) {
  if (typeof value === "string") return value.trim().toLowerCase();
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const action = (value as StreamEventRecord).action;
    return typeof action === "string" ? action.trim().toLowerCase() : "";
  }
  return "";
}

function streamEventSource(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const source = (value as StreamEventRecord).source;
  return typeof source === "string" ? source.trim().toLowerCase() : "";
}

function streamEventLabel(value: unknown) {
  const key = streamEventKey(value);
  if (key === "pause") {
    const source = streamEventSource(value);
    if (!source) return "Pausa";
    return playerActionSources.has(source) ? "Pausa dal player" : "Pausa del Guard";
  }
  return actionLabels[key] || key || "Nessuna azione registrata";
}

function streamTechnicalSignalLabel(value: unknown) {
  const key = typeof value === "string" ? value.trim().toLowerCase() : "";
  return technicalSignalLabels[key] || key;
}

function streamHistorySignalLabels({
  violations = [],
  actions = [],
}: {
  violations?: unknown[];
  actions?: unknown[];
}) {
  const labels = [
    ...violations.map(streamTechnicalSignalLabel),
    ...actions.map(streamEventLabel),
  ].filter(Boolean);
  return labels.filter((label, index) => labels.indexOf(label) === index);
}

export {
  streamEventKey,
  streamEventLabel,
  streamHistorySignalLabels,
  streamTechnicalSignalLabel,
};
