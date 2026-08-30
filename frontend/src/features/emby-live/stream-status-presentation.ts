import type { EmbyLiveTranscodeGuard } from "@/features/emby-live/types";

export type StreamStatusTone = "ok" | "info" | "warning" | "error" | "neutral";

export type StreamStatusPresentation = {
  label: string;
  tone: StreamStatusTone;
};

export function streamModePresentation(mode?: string | null): StreamStatusPresentation {
  const normalized = String(mode || "").trim().toLowerCase();

  if (normalized.includes("transcod")) {
    return { label: "Transcodifica", tone: "warning" };
  }
  if (normalized === "diretta" || normalized === "diretto" || normalized.includes("direct")) {
    return { label: "Diretto", tone: "ok" };
  }
  return { label: "Non disponibile", tone: "neutral" };
}

export function transcodeGuardPresentation(
  guard?: EmbyLiveTranscodeGuard,
): StreamStatusPresentation {
  if (!guard || typeof guard.should_enforce !== "boolean") {
    return { label: "Non valutato", tone: "neutral" };
  }
  return guard.should_enforce
    ? { label: "Violazione rilevata", tone: "warning" }
    : { label: "Conforme", tone: "ok" };
}
