import { LoaderCircle, X } from "@/components/ui/icons";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  getEmbyItemDetails,
  getEmbyMovieVersions,
  getEmbySeasonEpisodes,
  getEmbySeriesSeasons,
} from "@/features/research/api";
import type {
  AvailabilityEntry,
  EmbyEpisode,
  EmbyItemDetails,
  EmbyMovieVersion,
  EmbySeason,
  TmdbSearchResult,
} from "@/features/research/types";

type MovieVersionsQuery = UseQueryResult<
  { success: boolean; versions: EmbyMovieVersion[] },
  Error
>;
type SeasonsQuery = UseQueryResult<
  { success: boolean; seasons: EmbySeason[] },
  Error
>;
type EpisodesQuery = UseQueryResult<
  { success: boolean; episodes: EmbyEpisode[] },
  Error
>;
type ItemDetailsQuery = UseQueryResult<
  { success: boolean; details: EmbyItemDetails },
  Error
>;

function EmbyMediaBrowser({
  selected,
  server,
  onClose,
}: {
  selected: TmdbSearchResult;
  server: AvailabilityEntry;
  onClose: () => void;
}) {
  const serverId = server.server_id || "";
  const itemId = server.item_id || "";
  const isTv = selected.media_type === "tv";
  const [activeItemId, setActiveItemId] = useState(itemId);
  const [activeSeasonId, setActiveSeasonId] = useState("");
  const movies = useQuery({
    queryKey: ["emby-movie-versions", serverId, selected.tmdb_id],
    queryFn: () => getEmbyMovieVersions(serverId, selected.tmdb_id),
    enabled: Boolean(serverId && !isTv),
  });
  const seasons = useQuery({
    queryKey: ["emby-series-seasons", serverId, itemId],
    queryFn: () => getEmbySeriesSeasons(serverId, itemId),
    enabled: Boolean(serverId && itemId && isTv),
  });
  const episodes = useQuery({
    queryKey: ["emby-season-episodes", serverId, activeSeasonId],
    queryFn: () => getEmbySeasonEpisodes(serverId, activeSeasonId),
    enabled: Boolean(serverId && activeSeasonId && isTv),
  });
  const details = useQuery({
    queryKey: ["emby-item-details", serverId, activeItemId],
    queryFn: () => getEmbyItemDetails(serverId, activeItemId),
    enabled: Boolean(serverId && activeItemId),
  });

  useEffect(() => {
    setActiveItemId(itemId);
    setActiveSeasonId("");
  }, [itemId, serverId, selected.tmdb_id]);

  function changeActiveSeason(seasonId: string) {
    if (seasonId === activeSeasonId) return;
    setActiveSeasonId(seasonId);
    setActiveItemId("");
  }

  return (
    <section
      className="emby-media-browser"
      aria-label={`Dettagli Emby ${server.server_name || ""}`}
    >
      <header>
        <div>
          <span>Disponibile su Emby</span>
          <strong>{server.server_name || "Server Emby"}</strong>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Chiudi dettagli Emby"
          aria-label="Chiudi dettagli Emby"
          onClick={onClose}
        >
          <X size={16} aria-hidden="true" />
        </Button>
      </header>
      {isTv ? (
        <TvBrowser
          seasons={seasons}
          episodes={episodes}
          activeSeasonId={activeSeasonId}
          activeItemId={activeItemId}
          onSeasonChange={changeActiveSeason}
          onItemChange={setActiveItemId}
        />
      ) : (
        <MovieBrowser
          versions={movies}
          activeItemId={activeItemId}
          onItemChange={setActiveItemId}
        />
      )}
      <ItemDetails details={details} />
    </section>
  );
}

function MovieBrowser({
  versions,
  activeItemId,
  onItemChange,
}: {
  versions: MovieVersionsQuery;
  activeItemId: string;
  onItemChange: (itemId: string) => void;
}) {
  return (
    <BrowserSection title="Versioni">
      {versions.isLoading ? <Loading label="Caricamento versioni..." /> : null}
      {versions.error ? (
        <BrowserError message={versions.error.message} />
      ) : null}
      {versions.data?.versions?.length ? (
        <div className="emby-browser-options">
          {versions.data.versions.map((version, index) => (
            <button
              key={`${version.item_id || "version"}-${index}`}
              type="button"
              className={activeItemId === version.item_id ? "is-active" : ""}
              aria-pressed={activeItemId === version.item_id}
              onClick={() => version.item_id && onItemChange(version.item_id)}
            >
              <strong>{version.name || "Versione"}</strong>
              <span>
                {version.resolutions?.join(" · ") || "Dettagli media"}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </BrowserSection>
  );
}

function TvBrowser({
  seasons,
  episodes,
  activeSeasonId,
  activeItemId,
  onSeasonChange,
  onItemChange,
}: {
  seasons: SeasonsQuery;
  episodes: EpisodesQuery;
  activeSeasonId: string;
  activeItemId: string;
  onSeasonChange: (seasonId: string) => void;
  onItemChange: (itemId: string) => void;
}) {
  return (
    <>
      <BrowserSection title="Stagioni">
        {seasons.isLoading ? <Loading label="Caricamento stagioni..." /> : null}
        {seasons.error ? (
          <BrowserError message={seasons.error.message} />
        ) : null}
        {seasons.data?.seasons?.length ? (
          <div className="emby-browser-options emby-browser-options--compact">
            {seasons.data.seasons.map((season) => (
              <button
                key={season.season_id}
                type="button"
                className={
                  activeSeasonId === season.season_id ? "is-active" : ""
                }
                aria-pressed={activeSeasonId === season.season_id}
                onClick={() =>
                  season.season_id && onSeasonChange(season.season_id)
                }
              >
                {seasonLabel(season.season_number)}
                {season.episode_count ? (
                  <span>{season.episode_count} ep.</span>
                ) : null}
              </button>
            ))}
          </div>
        ) : null}
      </BrowserSection>
      {activeSeasonId ? (
        <BrowserSection title="Episodi">
          {episodes.isLoading ? (
            <Loading label="Caricamento episodi..." />
          ) : null}
          {episodes.error ? (
            <BrowserError message={episodes.error.message} />
          ) : null}
          {episodes.data?.episodes?.length ? (
            <div className="emby-browser-episodes">
              {episodes.data.episodes.map((episode) => (
                <EpisodeButton
                  key={episode.episode_id}
                  episode={episode}
                  activeItemId={activeItemId}
                  onItemChange={onItemChange}
                />
              ))}
            </div>
          ) : null}
        </BrowserSection>
      ) : null}
    </>
  );
}

function EpisodeButton({
  episode,
  activeItemId,
  onItemChange,
}: {
  episode: EmbyEpisode;
  activeItemId: string;
  onItemChange: (itemId: string) => void;
}) {
  const first = episode.resolutions?.[0];
  return (
    <button
      type="button"
      className={activeItemId === first?.item_id ? "is-active" : ""}
      aria-pressed={activeItemId === first?.item_id}
      onClick={() => first?.item_id && onItemChange(first.item_id)}
    >
      <strong>{`E${String(episode.episode_number || 0).padStart(2, "0")}`}</strong>
      <span>{episode.name || "Episodio"}</span>
      <small>
        {episode.resolutions
          ?.map((entry) => entry.label)
          .filter(Boolean)
          .join(" · ") || "Dettagli"}
      </small>
    </button>
  );
}

function ItemDetails({ details }: { details: ItemDetailsQuery }) {
  return (
    <BrowserSection title="Dettagli media">
      {details.isLoading ? <Loading label="Caricamento dettagli..." /> : null}
      {details.error ? <BrowserError message={details.error.message} /> : null}
      {details.data?.details ? (
        <dl className="emby-item-details">
          <Detail label="Titolo" value={details.data.details.title} />
          <Detail label="Risoluzione" value={details.data.details.resolution} />
          <Detail label="Video" value={details.data.details.video_codec} />
          <Detail label="Audio" value={details.data.details.audio_codec} />
          <Detail
            label="Bitrate"
            value={
              details.data.details.bitrate_mbps
                ? `${details.data.details.bitrate_mbps} Mbps`
                : ""
            }
          />
          <Detail label="Percorso" value={details.data.details.path} />
          <Detail
            label="Tracce audio"
            value={details.data.details.audio_tracks?.join(" · ")}
          />
        </dl>
      ) : null}
    </BrowserSection>
  );
}

function BrowserSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="emby-browser-section">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function Detail({
  label,
  value,
}: {
  label: string;
  value: string | number | undefined;
}) {
  return value ? (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  ) : null;
}

function Loading({ label }: { label: string }) {
  return (
    <span className="emby-browser-loading">
      <LoaderCircle size={14} className="animate-spin" aria-hidden="true" />{" "}
      {label}
    </span>
  );
}

function BrowserError({ message }: { message: string }) {
  return <p className="emby-browser-error" role="alert">{message}</p>;
}

function seasonLabel(number: number | undefined) {
  return number === 0 ? "Speciali" : `S${String(number || 0).padStart(2, "0")}`;
}

export { EmbyMediaBrowser };
