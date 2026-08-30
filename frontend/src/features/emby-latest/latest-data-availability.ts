import {
  formatBytes,
  formatLatestDate,
  formatRuntime,
} from "@/features/emby-latest/presentation";
import type { LatestChange, LatestItem } from "@/features/emby-latest/types";

type LatestVerificationKind = "movie" | "series";

type LatestVerificationField = {
  field: string;
  label: string;
  source: string;
  value: unknown;
};

type LatestVerificationCollection = {
  available: LatestVerificationField[];
  missing: LatestVerificationField[];
  added: LatestVerificationField[];
};

type LatestVerificationFile = {
  label: string;
  available: LatestVerificationField[];
  missing: LatestVerificationField[];
};

type LatestVerification = {
  common: LatestVerificationCollection;
  files: LatestVerificationFile[];
};

const optionalAudioLanguageFields = new Set([
  "audio_ita",
  "audio_eng",
  "audio_fra",
  "audio_spa",
  "audio_ger",
  "audio_jpn",
]);

const mediaInfoFields = new Set([
  "quality",
  "resolution",
  "video_codec",
  "audio_codec",
  "audio_channels",
  "container",
  "bitrate",
  "size",
  "source_name",
  "path",
  "video_details",
  "audio_details",
  "audio_ita",
  "audio_eng",
  "audio_fra",
  "audio_spa",
  "audio_ger",
  "audio_jpn",
  "audio_langs",
  "subtitle_langs",
]);

const fieldLabels: Record<string, string> = {
  title: "Titolo",
  original_title: "Titolo originale",
  year: "Anno",
  overview: "Trama",
  genres: "Generi",
  community_rating: "Rating Emby",
  official_rating: "Classificazione",
  runtime_minutes: "Durata",
  premiere_date: "Data uscita",
  tagline: "Tagline",
  studios: "Studios",
  cast: "Cast",
  directors: "Registi",
  creators: "Creatori",
  image_url: "Poster (cache DB)",
  poster_url: "Poster Emby",
  emby_url: "Link Emby",
  library_name: "Libreria",
  server_name: "Server",
  jellyseerr_requested: "Jellyseerr richiesto",
  jellyseerr_request_status_label: "Jellyseerr stato",
  jellyseerr_request_status: "Jellyseerr stato tecnico",
  jellyseerr_request_id: "Jellyseerr ID richiesta",
  jellyseerr_requested_by: "Jellyseerr richiesto da",
  series_name: "Nome serie",
  season_number: "Numero stagione",
  episode_number: "Numero episodio",
  episode_title: "Titolo episodio",
  season_count: "Numero stagioni",
  episode_count: "Numero episodi",
  tmdb_id: "TMDB ID",
  tmdb_rating: "TMDB rating",
  tmdb_votes: "TMDB voti",
  tmdb_poster_url: "TMDB poster",
  tmdb_backdrop_url: "TMDB backdrop",
  tmdb_logo_url: "TMDB logo",
  tmdb_banner_url: "TMDB banner",
  tmdb_thumb_url: "TMDB thumb",
  imdb_id: "IMDb ID",
  imdb_rating: "IMDb rating",
  imdb_votes: "IMDb voti",
  metacritic_rating: "Metacritic",
  tvdb_id: "TVDB ID",
  trakt_id: "Trakt ID",
  trakt_rating: "Trakt rating",
  trakt_votes: "Trakt voti",
  quality: "Qualita",
  resolution: "Risoluzione",
  video_codec: "Codec video",
  audio_codec: "Codec audio",
  audio_channels: "Canali audio",
  container: "Container",
  bitrate: "Bitrate",
  size: "Dimensione",
  source_name: "Nome sorgente",
  path: "Percorso",
  added_at: "Data aggiunta",
  video_details: "Dettagli video",
  audio_details: "Dettagli audio",
  audio_ita: "Audio italiano",
  audio_eng: "Audio inglese",
  audio_fra: "Audio francese",
  audio_spa: "Audio spagnolo",
  audio_ger: "Audio tedesco",
  audio_jpn: "Audio giapponese",
  audio_langs: "Lingue audio",
  subtitle_langs: "Lingue sottotitoli",
};

function hasLatestVerificationValue(value: unknown) {
  return Array.isArray(value)
    ? value.length > 0
    : value !== null && value !== undefined && value !== "" && value !== 0;
}

function fieldSource(field: string, kind: LatestVerificationKind) {
  if (field.startsWith("tmdb_")) return "TMDB";
  if (field.startsWith("imdb_") || field === "metacritic_rating")
    return "MDBList / OMDB";
  if (field.startsWith("trakt_")) return "Trakt";
  if (field.startsWith("jellyseerr_")) return "Jellyseerr";
  if (field === "image_url") return "Cache DB";
  if (field === "tvdb_id" && kind === "series") return "OMDB";
  if (
    field.startsWith("audio_") ||
    field.startsWith("video_") ||
    field === "subtitle_langs"
  )
    return "Emby MediaStreams";
  if (
    [
      "quality",
      "resolution",
      "audio_codec",
      "audio_channels",
      "container",
      "bitrate",
      "size",
      "source_name",
      "path",
      "added_at",
    ].includes(field)
  )
    return "Emby MediaSources";
  return "Emby";
}

function commonFields(kind: LatestVerificationKind) {
  const fields = [
    "title",
    "original_title",
    "year",
    "overview",
    "genres",
    "community_rating",
    "official_rating",
    "runtime_minutes",
    "premiere_date",
    "tagline",
    "studios",
    "cast",
    "image_url",
    "poster_url",
    "emby_url",
    "library_name",
    "server_name",
    "jellyseerr_requested",
    "jellyseerr_request_status_label",
    "jellyseerr_request_status",
    "jellyseerr_request_id",
    "jellyseerr_requested_by",
    "tmdb_id",
    "tmdb_rating",
    "tmdb_votes",
    "tmdb_poster_url",
    "tmdb_backdrop_url",
    "tmdb_logo_url",
    "tmdb_banner_url",
    "tmdb_thumb_url",
    "imdb_id",
    "imdb_rating",
    "imdb_votes",
    "metacritic_rating",
    "trakt_id",
    "trakt_rating",
    "trakt_votes",
  ];
  if (kind === "series")
    return [...fields, "series_name", "season_count", "episode_count", "creators", "tvdb_id"];
  return [...fields, "directors"];
}

function fileFields(kind: LatestVerificationKind) {
  const fields = [
    "quality",
    "resolution",
    "video_codec",
    "audio_codec",
    "audio_channels",
    "container",
    "bitrate",
    "size",
    "source_name",
    "path",
    "added_at",
    "video_details",
    "audio_details",
    "audio_ita",
    "audio_eng",
    "audio_fra",
    "audio_spa",
    "audio_ger",
    "audio_jpn",
    "audio_langs",
    "subtitle_langs",
  ];
  return kind === "series"
    ? [...fields, "season_number", "episode_number", "episode_title"]
    : fields;
}

function hasAudioProbeData(source: Record<string, unknown>) {
  return (
    hasLatestVerificationValue(source.audio_langs) ||
    hasLatestVerificationValue(source.audio_details)
  );
}

function fieldList(
  fields: string[],
  source: Record<string, unknown>,
  kind: LatestVerificationKind,
  baseline?: Record<string, unknown>,
) {
  const available: LatestVerificationField[] = [];
  const missing: LatestVerificationField[] = [];
  const added: LatestVerificationField[] = [];
  for (const field of fields) {
    const value = source[field];
    const entry = {
      field,
      label: fieldLabels[field] || field,
      source: fieldSource(field, kind),
      value,
    };
    if (hasLatestVerificationValue(value)) {
      available.push(entry);
      if (baseline && !hasLatestVerificationValue(baseline[field])) added.push(entry);
      continue;
    }
    if (mediaInfoFields.has(field) && source.mediainfo_available === true) continue;
    if (optionalAudioLanguageFields.has(field) && hasAudioProbeData(source)) continue;
    missing.push(entry);
  }
  return { available, missing, added };
}

function normalizeFileName(value: unknown) {
  if (!value) return "";
  let filename = String(value).split(/[?#]/)[0];
  const parts = filename.split(/[\\/]/).filter(Boolean);
  filename = parts.at(-1) || "";
  try {
    filename = decodeURIComponent(filename);
  } catch {
    // Keep the original source name when the URL contains invalid escapes.
  }
  return filename.replace(/\.[a-z0-9]{2,5}$/i, "").replace(/_+/g, " ").trim();
}

function fileLabel(change: LatestChange, index: number) {
  const episode =
    Number.isFinite(Number(change.season_number)) &&
    Number.isFinite(Number(change.episode_number))
      ? `S${String(change.season_number).padStart(2, "0")}E${String(change.episode_number).padStart(2, "0")}`
      : "";
  const descriptor = [
    normalizeFileName(change.path),
    change.source_name ? String(change.source_name) : "",
    episode,
    change.episode_title,
  ].find(Boolean);
  return descriptor ? `File ${index + 1} · ${descriptor}` : `File ${index + 1}`;
}

function latestVerification(
  item: LatestItem,
  kind: LatestVerificationKind,
  baseline?: LatestItem,
): LatestVerification {
  const common = fieldList(commonFields(kind), item, kind, baseline);
  return {
    common,
    files: (item.changes || []).map((change, index) => ({
      label: fileLabel(change, index),
      ...fieldList(fileFields(kind), change, kind),
    })),
  };
}

function formatLatestVerificationValue(field: string, value: unknown) {
  if (!hasLatestVerificationValue(value)) return "Non disponibile";
  if (field.includes("_url")) return "Disponibile";
  if (field === "runtime_minutes" && typeof value === "number")
    return formatRuntime(value) || String(value);
  if (field === "size" && typeof value === "number") return formatBytes(value) || String(value);
  if (field === "bitrate") return `${value} Mbps`;
  if (field === "added_at") return formatLatestDate(String(value)) || String(value);
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "boolean") return value ? "Si" : "No";
  const text = String(value);
  return field === "overview" || field === "path"
    ? `${text.slice(0, 100)}${text.length > 100 ? "..." : ""}`
    : text;
}

export {
  formatLatestVerificationValue,
  hasLatestVerificationValue,
  latestVerification,
};
export type {
  LatestVerification,
  LatestVerificationCollection,
  LatestVerificationField,
  LatestVerificationFile,
  LatestVerificationKind,
};
