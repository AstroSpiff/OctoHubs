import { LoaderCircle } from "@/components/ui/icons";

import { SearchResultTable } from "@/features/research/components/search-result-table";
import { searchProgressMessage } from "@/features/research/search-progress";
import type {
  SearchResult,
  StreamingSearchProgress,
} from "@/features/research/types";

function SearchResults({
  results,
  qbittorrentAvailable,
  searching,
  progress,
}: {
  results: SearchResult[];
  qbittorrentAvailable: boolean;
  searching: boolean;
  progress: StreamingSearchProgress;
}) {
  const liveProgress = searchProgressMessage(progress);

  return (
    <section
      className="research-card research-results-card"
      aria-labelledby="research-results-title"
    >
      <header className="research-card-heading">
        <div>
          <h3 id="research-results-title" className="contextual-heading" title="Risultati">Risultati ricerca</h3>
          <p role={searching ? "status" : undefined}>
            {searching
              ? liveProgress
              : results.length
                ? `${results.length} risultati nell'ordine configurato.`
                : "Avvia una ricerca per visualizzare i risultati."}
          </p>
        </div>
      </header>
      {searching && !results.length ? (
        <div className="research-result-loading">
          <LoaderCircle className="animate-spin" size={20} aria-hidden="true" />{" "}
          {liveProgress}
        </div>
      ) : null}
      {results.length ? (
        <SearchResultTable
          results={results}
          qbittorrentAvailable={qbittorrentAvailable}
        />
      ) : null}
    </section>
  );
}

export { SearchResults };
