import { useId, useState } from "react";
import type { KeyboardEvent } from "react";

import { tabAtKey } from "@/components/ui/tab-navigation";

function RequestSeasonStatus({ seasons }: { seasons: Array<Record<string, unknown>> }) {
  const instanceId = useId().replace(/:/g, "");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const selected = seasons[selectedIndex] || seasons[0];
  const episodes = Array.isArray(selected?.episodes)
    ? selected.episodes.filter((episode): episode is Record<string, unknown> => Boolean(episode) && typeof episode === "object")
    : [];
  const pending = Array.isArray(selected?.pending) ? selected.pending : [];

  function selectSeasonFromKeyboard(event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    const nextId = tabAtKey(seasons.map((_, index) => String(index)), String(currentIndex), event.key);
    if (nextId === undefined) return;
    event.preventDefault();
    const nextIndex = Number(nextId);
    setSelectedIndex(nextIndex);
    window.requestAnimationFrame(() => document.getElementById(`research-season-${instanceId}-tab-${nextIndex}`)?.focus());
  }

  return <div className="research-request-seasons">
    <div className="research-request-season-tabs" role="tablist" aria-label="Stagioni richiesta">
      {seasons.map((season, index) => <button key={`${season.season || "season"}-${index}`} id={`research-season-${instanceId}-tab-${index}`} type="button" role="tab" aria-selected={selected === season} aria-controls={`research-season-${instanceId}-panel-${index}`} tabIndex={selected === season ? 0 : -1} className={selected === season ? "is-active" : ""} onClick={() => setSelectedIndex(index)} onKeyDown={(event) => selectSeasonFromKeyboard(event, index)}>
        {`S${String(season.season || 0).padStart(2, "0")}`} {String(season.status_display || season.status || "")}
      </button>)}
    </div>
    {selected ? <div id={`research-season-${instanceId}-panel-${selectedIndex}`} className="research-request-episodes" role="tabpanel" aria-labelledby={`research-season-${instanceId}-tab-${selectedIndex}`} tabIndex={0}>
      {episodes.length ? episodes.map((episode, index) => <span key={`${episode.episode || "episode"}-${index}`} className={`is-${String(episode.status || "unknown")}`} title={episodeJustWatchTitle(episode)}>
        E{String(episode.episode || 0).padStart(2, "0")}{episode.justwatch ? " JW" : ""}{episode.status === "unreleased" && episode.release ? <small>{String(episode.release)}</small> : null}
      </span>) : pending.length ? pending.map((episode) => <span key={String(episode)} className="is-pending">E{String(episode).padStart(2, "0")}</span>) : " Nessun episodio rilevato"}
    </div> : null}
  </div>;
}

function episodeJustWatchTitle(episode: Record<string, unknown>) {
  const providers = Array.isArray(episode.justwatch_providers)
    ? episode.justwatch_providers.filter((entry): entry is string => typeof entry === "string" && Boolean(entry))
    : [];
  return providers.length ? `Disponibile su JustWatch: ${providers.join(", ")}` : undefined;
}

export { RequestSeasonStatus };
