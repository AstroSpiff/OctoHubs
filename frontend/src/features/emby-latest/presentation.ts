import type { LatestChange, LatestItem } from "@/features/emby-latest/types";

export function formatLatestDate(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
  }).format(date);
}

export function formatLatestAge(value?: string | null) {
  if (!value) return "Aggiornato ora";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Aggiornato";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `Ultimo aggiornamento: ${seconds}s fa`;
  if (seconds < 3600)
    return `Ultimo aggiornamento: ${Math.floor(seconds / 60)} min fa`;
  return `Ultimo aggiornamento: ${Math.floor(seconds / 3600)} h fa`;
}

export function formatRuntime(value?: number) {
  if (!value || value <= 0) return "";
  const hours = Math.floor(value / 60);
  const minutes = Math.round(value % 60);
  return hours
    ? minutes
      ? `${hours}h ${minutes}m`
      : `${hours}h`
    : `${minutes}m`;
}

export function formatBytes(value?: number) {
  if (!value || value <= 0) return "";
  const gigabytes = value / (1024 * 1024 * 1024);
  return gigabytes >= 1
    ? `${gigabytes.toFixed(2)} GB`
    : `${Math.round(value / (1024 * 1024))} MB`;
}

export function formatEpisode(
  season: LatestChange["season_number"],
  episode: LatestChange["episode_number"],
) {
  const seasonNumber = Number(season);
  const episodeNumber = Number(episode);
  if (
    !Number.isInteger(seasonNumber) ||
    seasonNumber < 0 ||
    !Number.isInteger(episodeNumber) ||
    episodeNumber <= 0
  )
    return "";
  return `S${String(seasonNumber).padStart(2, "0")}E${String(episodeNumber).padStart(2, "0")}`;
}

export function changeTitle(change: LatestChange) {
  const episode = formatEpisode(change.season_number, change.episode_number);
  const suffix = change.episode_title ? ` - ${change.episode_title}` : "";
  switch (change.kind) {
    case "new_movie":
      return "Nuovo film";
    case "new_series":
      return "Nuova serie";
    case "new_season":
      return change.season_number === null || change.season_number === undefined
        ? "Nuova stagione"
        : `Nuova stagione ${change.season_number}`;
    case "new_episode":
      return episode ? `Nuovo episodio ${episode}${suffix}` : "Nuovo episodio";
    case "existing_file":
      return episode ? `File ${episode}${suffix}` : "File";
    case "new_version":
      return episode ? `Nuova versione ${episode}` : "Nuova versione";
    default:
      return "Aggiornamento";
  }
}

export function changeDetails(change: LatestChange) {
  return [
    change.quality,
    change.video_codec,
    change.audio_codec,
    formatBytes(change.size),
    formatLatestDate(change.added_at)
      ? `Aggiunto ${formatLatestDate(change.added_at)}`
      : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function visibleLatestItems(
  items: LatestItem[],
  serverId: string,
  perServerLimit: number,
) {
  const target = latestItemsForServer(items, serverId);
  if (serverId !== "all") return target.slice(0, perServerLimit);
  const counts = new Map<string, number>();
  return target.filter((item) => {
    const key = item.server_id || "unknown";
    const count = counts.get(key) || 0;
    if (count >= perServerLimit) return false;
    counts.set(key, count + 1);
    return true;
  });
}

export function latestItemsForServer(items: LatestItem[], serverId: string) {
  return serverId === "all"
    ? items
    : items.filter((item) => item.server_id === serverId);
}

export function latestPreviewItemLabel(item: LatestItem) {
  const title = `${item.title || "Titolo"}${item.year ? ` (${item.year})` : ""}`;
  const details = [
    item.update_label,
    item.server_name,
    formatLatestDate(item.added_at || item.premiere_date),
  ].filter(Boolean);

  return details.length ? `${title} · ${details.join(" · ")}` : title;
}
