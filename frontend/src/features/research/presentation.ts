import type { SearchResult } from "@/features/research/types";

function displayMediaType(mediaType: string | undefined) {
  if (mediaType === "movie") return "Film";
  if (mediaType === "tv") return "Serie TV";
  return "Non definito";
}

function displayFileSize(size: number | undefined) {
  return typeof size === "number" && Number.isFinite(size) ? `${size.toFixed(size >= 10 ? 1 : 2)} GB` : "-";
}

function resultSortBySeeders(results: SearchResult[]) {
  return [...results].sort((left, right) => (right.seeders || 0) - (left.seeders || 0));
}

function torrentDownloadLink(result: SearchResult) {
  return [result.torrent, result.link].find((candidate): candidate is string =>
    typeof candidate === "string" && /^https?:\/\//i.test(candidate),
  ) || null;
}

function magnetExportLink(result: SearchResult) {
  return [result.magnet, result.magnetUri, result.magnetUrl].find((candidate): candidate is string =>
    typeof candidate === "string" && /^magnet:/i.test(candidate),
  ) || null;
}

function tmdbPosterUrl(path: string | undefined) {
  if (!path) return null;
  return path.startsWith("http://") || path.startsWith("https://") ? path : `https://image.tmdb.org/t/p/w154${path}`;
}

function formatResearchDate(value: string | undefined | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export { displayFileSize, displayMediaType, formatResearchDate, magnetExportLink, resultSortBySeeders, tmdbPosterUrl, torrentDownloadLink };
