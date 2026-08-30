import type { Severity } from "@/components/ui/badge";
import type {
  EmbyLiveServer,
  EmbyLiveStream,
} from "@/features/emby-live/types";

export function formatLiveTime(value?: string | null) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime())
    ? new Intl.DateTimeFormat("it-IT", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(date)
    : "Mai";
}

export function serverPresentation(server: EmbyLiveServer): {
  label: string;
  severity: Severity;
} {
  if (!server.server.enabled)
    return { label: "Disabilitato", severity: "neutral" };
  if (server.status.ok) return { label: "Connesso", severity: "ok" };
  return { label: "Errore", severity: "error" };
}

export function streamProgress(stream: EmbyLiveStream) {
  return typeof stream.playback_percent === "number" &&
    Number.isFinite(stream.playback_percent)
    ? clampPercentage(stream.playback_percent)
    : null;
}

export function taskProgress(value?: number) {
  return typeof value === "number" && Number.isFinite(value)
    ? clampPercentage(value)
    : 0;
}

export function streamPlaybackSummary(stream: EmbyLiveStream): string {
  const position = [stream.position, stream.duration]
    .filter(Boolean)
    .join(" / ");
  const progress = streamProgress(stream);
  return (
    [position, progress !== null ? `${progress}%` : ""]
      .filter(Boolean)
      .join(" · ") || "Avanzamento non disponibile"
  );
}

export function streamDisplayTitle(stream: EmbyLiveStream): string {
  const episodeCode =
    Number.isInteger(stream.season_number) &&
    Number.isInteger(stream.episode_number)
      ? `S${String(stream.season_number).padStart(2, "0")}E${String(stream.episode_number).padStart(2, "0")}`
      : "";
  const title = stream.series_name || stream.title || "Riproduzione";
  return [
    title,
    stream.year ? `(${stream.year})` : "",
    episodeCode,
    stream.episode_title || "",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function streamFlowSummary(stream: EmbyLiveStream): string {
  const source = stream.stream_container || stream.container || "N/D";
  const target = stream.transcode_container;
  const bitrate = target ? stream.transcode_bitrate : stream.bitrate;
  const bitrateLabel = formatStreamBitrate(bitrate);
  return `${source}${target ? ` -> ${target}` : ""}${bitrateLabel ? ` (${bitrateLabel})` : ""}`;
}

function formatStreamBitrate(value?: number): string {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? `${Math.round(value / 1000)} kbps`
    : "";
}

function clampPercentage(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}
