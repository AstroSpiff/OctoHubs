import { LoaderCircle, Search, Send } from "@/components/ui/icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  getTmdbTvDetails,
  requestFromJellyseerr,
} from "@/features/research/api";
import {
  customRulesFromSearchRules,
  loadStoredCustomRules,
  storeCustomRules,
} from "@/features/research/customization";
import { SearchAdvancedOptions } from "@/features/research/components/search-advanced-options";
import { TmdbSearchPicker } from "@/features/research/components/tmdb-search-picker";
import type { ManualSearchQuery } from "@/features/research/manual-search-query";
import type {
  CustomSearchRules,
  ResearchOverview,
  ResearchMediaType,
  ResearchNotice,
  StreamingSearchInput,
  TmdbSearchResult,
} from "@/features/research/types";
import {
  StreamingSearchPartialError,
  StreamingSearchSupersededError,
} from "@/features/research/use-streaming-search";

type IndependentSearchFormProps = {
  overview: ResearchOverview;
  initialSearch?: ManualSearchQuery | StreamingSearchInput | null;
  searching: boolean;
  onSearch: (input: {
    query: string;
    mediaType: ResearchMediaType;
    indexers: Array<"prowlarr" | "jackett">;
    tmdbId?: number;
    seasons: number[];
    customRules?: CustomSearchRules;
  }) => Promise<void>;
  onSearchStart: () => void;
  onCancel?: () => void;
};

function IndependentSearchForm({
  overview,
  initialSearch,
  searching,
  onSearch,
  onSearchStart,
  onCancel,
}: IndependentSearchFormProps) {
  const initialized = useRef(false);
  const initializedSeasonSelectionRef = useRef<string | null>(null);
  const jellyseerrRequestGenerationRef = useRef(0);
  const [query, setQuery] = useState("");
  const [mediaType, setMediaType] = useState<ResearchMediaType>("unknown");
  const [selected, setSelected] = useState<TmdbSearchResult | null>(null);
  const [seasons, setSeasons] = useState<number[]>([]);
  const [customize, setCustomize] = useState(false);
  const [useProwlarr, setUseProwlarr] = useState(true);
  const [useJackett, setUseJackett] = useState(false);
  const [customRules, setCustomRules] = useState<CustomSearchRules>(() =>
    customRulesFromSearchRules({}),
  );
  const [notice, setNotice] = useState<ResearchNotice | null>(null);
  const [requesting, setRequesting] = useState(false);
  const tvDetails = useQuery({
    queryKey: ["tmdb-tv-details", selected?.tmdb_id],
    queryFn: () => getTmdbTvDetails(selected?.tmdb_id || 0),
    enabled: selected?.media_type === "tv",
    staleTime: 5 * 60_000,
  });
  const defaultCustomRules = useMemo<CustomSearchRules>(
    () => ({
      ...customRulesFromSearchRules(overview.search_rules),
      target_languages: overview.search_defaults.target_languages,
      exclude_tags: overview.search_defaults.exclude_tags,
    }),
    [
      overview.search_defaults.exclude_tags,
      overview.search_defaults.target_languages,
      overview.search_rules,
    ],
  );

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    setUseProwlarr(overview.search_rules.use_prowlarr !== false);
    setUseJackett(Boolean(overview.search_rules.use_jackett));
    const restored = loadStoredCustomRules(defaultCustomRules);
    setCustomize(restored.enabled);
    setCustomRules(restored.value);
  }, [
    overview.search_rules.use_jackett,
    overview.search_rules.use_prowlarr,
    defaultCustomRules,
  ]);

  useEffect(() => {
    const selectionKey = seasonSelectionKey(selected);
    if (
      !selectionKey ||
      initializedSeasonSelectionRef.current === selectionKey ||
      !tvDetails.data?.details.seasons
    )
      return;
    initializedSeasonSelectionRef.current = selectionKey;
    setSeasons(
      tvDetails.data.details.seasons
        .filter((season) => season.season_number > 0)
        .map((season) => season.season_number),
    );
  }, [selected, tvDetails.data?.details.seasons]);

  useEffect(() => {
    if (!initialSearch) return;
    jellyseerrRequestGenerationRef.current += 1;
    setRequesting(false);
    setQuery(initialSearch.query);
    setMediaType(initialSearch.mediaType);
    if (isStreamingSearchInput(initialSearch)) {
      const restoredSelection =
        initialSearch.tmdbId && initialSearch.mediaType !== "unknown"
          ? {
              tmdb_id: initialSearch.tmdbId,
              title: initialSearch.query,
              media_type: initialSearch.mediaType,
            }
          : null;
      setUseProwlarr(initialSearch.indexers.includes("prowlarr"));
      setUseJackett(initialSearch.indexers.includes("jackett"));
      initializedSeasonSelectionRef.current =
        seasonSelectionKey(restoredSelection);
      setSeasons([...initialSearch.seasons]);
      setCustomize(Boolean(initialSearch.customRules));
      if (initialSearch.customRules) setCustomRules(initialSearch.customRules);
      setSelected(restoredSelection);
    } else {
      initializedSeasonSelectionRef.current = null;
      setSelected(null);
      setSeasons([]);
    }
    setNotice(null);
  }, [initialSearch]);

  function selectTitle(title: TmdbSearchResult) {
    jellyseerrRequestGenerationRef.current += 1;
    setRequesting(false);
    initializedSeasonSelectionRef.current = null;
    setSelected(title);
    setQuery([title.title, title.year].filter(Boolean).join(" "));
    setMediaType(title.media_type);
    setSeasons([]);
    setNotice(null);
  }

  function clearTitle() {
    jellyseerrRequestGenerationRef.current += 1;
    setRequesting(false);
    initializedSeasonSelectionRef.current = null;
    setSelected(null);
    setSeasons([]);
    setNotice(null);
  }

  function changeMediaType(nextMediaType: ResearchMediaType) {
    setMediaType(nextMediaType);
    if (!selected || selected.media_type === nextMediaType) return;
    jellyseerrRequestGenerationRef.current += 1;
    setRequesting(false);
    initializedSeasonSelectionRef.current = null;
    setSelected(null);
    setSeasons([]);
    setNotice(null);
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    const indexers = [
      useProwlarr ? "prowlarr" : null,
      useJackett ? "jackett" : null,
    ].filter((entry): entry is "prowlarr" | "jackett" => entry !== null);
    if (!trimmedQuery) {
      setNotice({ message: "Inserisci un termine di ricerca.", tone: "error" });
      return;
    }
    if (!indexers.length) {
      setNotice({ message: "Seleziona almeno un indexer.", tone: "error" });
      return;
    }
    setNotice(null);
    onSearchStart();
    try {
      await onSearch({
        query: trimmedQuery,
        mediaType,
        indexers,
        ...(selected ? { tmdbId: selected.tmdb_id } : {}),
        seasons,
        ...(customize ? { customRules } : {}),
      });
      setNotice({
        message: "Ricerca completata. Lo storico è disponibile qui sotto.",
        tone: "success",
      });
    } catch (reason) {
      if (reason instanceof StreamingSearchSupersededError) return;
      if (reason instanceof StreamingSearchPartialError) {
        setNotice({ message: reason.message, tone: "warning" });
        return;
      }
      setNotice({
        message:
          reason instanceof Error ? reason.message : "Ricerca non riuscita.",
        tone: "error",
      });
    }
  }

  async function createJellyseerrRequest() {
    if (!selected) return;
    if (selected.media_type === "tv" && tvSeasonSelectionUnavailable) {
      setNotice({
        message: "Seleziona almeno una stagione prima di inviare la richiesta.",
        tone: "error",
      });
      return;
    }
    const requestGeneration = jellyseerrRequestGenerationRef.current + 1;
    jellyseerrRequestGenerationRef.current = requestGeneration;
    const requestedTitle = selected;
    const requestedSeasons = [...seasons];
    setRequesting(true);
    setNotice(null);
    try {
      const response = await requestFromJellyseerr(
        requestedTitle.tmdb_id,
        requestedTitle.media_type,
        requestedSeasons,
      );
      if (jellyseerrRequestGenerationRef.current !== requestGeneration) return;
      setNotice({
        message: response.message || "Richiesta inviata a Jellyseerr.",
        tone: response.success ? "success" : "error",
      });
    } catch (reason) {
      if (jellyseerrRequestGenerationRef.current !== requestGeneration) return;
      setNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Invio a Jellyseerr non riuscito.",
        tone: "error",
      });
    } finally {
      if (jellyseerrRequestGenerationRef.current === requestGeneration) {
        setRequesting(false);
      }
    }
  }

  const availableSeasons = tvDetails.data?.details.seasons || [];
  const tvSeasonSelectionUnavailable =
    selected?.media_type === "tv" &&
    (tvDetails.isLoading ||
      tvDetails.isError ||
      availableSeasons.length === 0 ||
      seasons.length === 0);
  return (
    <section
      className="research-card"
      aria-labelledby="independent-search-title"
    >
      <header className="research-card-heading">
        <div>
          <h3 id="independent-search-title" className="contextual-heading" title="Ricerca manuale">Parametri ricerca</h3>
          <p>
            Interroga gli indexer senza applicare le regole automatiche delle
            richieste Jellyseerr.
          </p>
        </div>
      </header>
      <form className="independent-search-form" onSubmit={submit}>
        <div className="research-query-row">
          <div className="research-query-field">
            <label htmlFor="research-query">Titolo</label>
            <TmdbSearchPicker
              query={query}
              selected={selected}
              onQueryChange={setQuery}
              onSelect={selectTitle}
              onClear={clearTitle}
            />
          </div>
          <div className="research-media-field">
            <label htmlFor="research-media-type">Tipo media</label>
            <select
              id="research-media-type"
              value={mediaType}
              onChange={(event) =>
                changeMediaType(event.target.value as ResearchMediaType)
              }
            >
              <option value="unknown">Non definito</option>
              <option value="movie">Film</option>
              <option value="tv">Serie TV</option>
            </select>
          </div>
        </div>
        {selected?.media_type === "tv" ? (
          <fieldset className="research-seasons">
            <legend>Stagioni</legend>
            {tvDetails.isLoading ? (
              <span>
                <LoaderCircle size={14} className="animate-spin" /> Caricamento
                stagioni...
              </span>
            ) : tvDetails.isError ? (
              <span className="inline-alert inline-alert--error" role="alert">
                {tvDetails.error.message}
                <Button type="button" variant="ghost" size="compact" onClick={() => void tvDetails.refetch()}>
                  Riprova
                </Button>
              </span>
            ) : availableSeasons.length ? (
              availableSeasons.map((season) => (
                <label key={season.season_number}>
                  <input
                    type="checkbox"
                    checked={seasons.includes(season.season_number)}
                    onChange={(event) => {
                      initializedSeasonSelectionRef.current =
                        seasonSelectionKey(selected);
                      setSeasons((current) =>
                        event.target.checked
                          ? [...current, season.season_number]
                          : current.filter(
                              (number) => number !== season.season_number,
                            ),
                      );
                    }}
                  />
                  {season.season_number === 0
                    ? "Speciali"
                    : `S${String(season.season_number).padStart(2, "0")}`}
                </label>
              ))
            ) : (
              <span className="inline-alert inline-alert--error" role="alert">
                Nessuna stagione disponibile per questa serie.
              </span>
            )}
          </fieldset>
        ) : null}
        <div className="research-options-row">
          <fieldset>
            <legend>Indexer</legend>
            <label className="research-toggle">
              <input
                type="checkbox"
                checked={useProwlarr}
                onChange={(event) => setUseProwlarr(event.target.checked)}
              />{" "}
              <span>Prowlarr</span>
            </label>
            <label className="research-toggle">
              <input
                type="checkbox"
                checked={useJackett}
                onChange={(event) => setUseJackett(event.target.checked)}
              />{" "}
              <span>Jackett</span>
            </label>
          </fieldset>
          <label className="research-toggle research-toggle--custom">
            <input
              type="checkbox"
              checked={customize}
              onChange={(event) => {
                const enabled = event.target.checked;
                setCustomize(enabled);
                storeCustomRules(enabled, customRules);
              }}
            />
            <span>Personalizza regole</span>
          </label>
        </div>
        {customize ? (
          <SearchAdvancedOptions
            defaultOpen
            mediaType={mediaType}
            value={customRules}
            onChange={(value) => {
              setCustomRules(value);
              storeCustomRules(true, value);
            }}
            movieOptions={overview.movie_sort_options}
            tvOptions={overview.tv_sort_options}
          />
        ) : null}
        {notice ? (
          <div
            className={`inline-alert inline-alert--${notice.tone}`}
            role={notice.tone === "error" ? "alert" : "status"}
          >
            {notice.message}
          </div>
        ) : null}
        <footer className="research-card-actions">
          <Button type="submit" requiresWriteAccess variant="primary" disabled={searching}>
            {searching ? (
              <>
                <LoaderCircle
                  className="animate-spin"
                  size={16}
                  aria-hidden="true"
                />{" "}
                Ricerca in corso...
              </>
            ) : (
              <>
                <Search size={16} aria-hidden="true" /> Cerca
              </>
            )}
          </Button>
          {searching && onCancel ? (
            <Button
              type="button"
              requiresWriteAccess
              variant="secondary"
              onClick={onCancel}
            >
              Annulla
            </Button>
          ) : null}
          {selected ? (
            <Button
              type="button"
              requiresWriteAccess
              variant="secondary"
              onClick={() => void createJellyseerrRequest()}
              disabled={requesting || tvSeasonSelectionUnavailable}
            >
              <Send size={16} aria-hidden="true" />
              {requesting ? "Invio..." : "Richiedi a Jellyseerr"}
            </Button>
          ) : null}
        </footer>
      </form>
    </section>
  );
}

function isStreamingSearchInput(
  value: ManualSearchQuery | StreamingSearchInput,
): value is StreamingSearchInput {
  return "indexers" in value;
}

function seasonSelectionKey(selected: TmdbSearchResult | null) {
  return selected?.media_type === "tv" ? `tv:${selected.tmdb_id}` : null;
}

export { IndependentSearchForm };
