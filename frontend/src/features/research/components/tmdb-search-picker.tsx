import { Check, Film, LoaderCircle, Search, Tv, X } from "@/components/ui/icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { checkEmbyAvailability, searchTmdb } from "@/features/research/api";
import { EmbyMediaBrowser } from "@/features/research/components/emby-media-browser";
import {
  displayMediaType,
  tmdbPosterUrl,
} from "@/features/research/presentation";
import {
  nextTmdbSuggestionIndex,
  tmdbSuggestionDomId,
} from "@/features/research/tmdb-suggestion-navigation";
import type { TmdbSearchResult } from "@/features/research/types";

type TmdbSearchPickerProps = {
  query: string;
  selected: TmdbSearchResult | null;
  onClear: () => void;
  onQueryChange: (value: string) => void;
  onSelect: (result: TmdbSearchResult) => void;
};

function TmdbSearchPicker({
  selected,
  ...props
}: TmdbSearchPickerProps) {
  const targetKey = selected
    ? `${selected.media_type}:${selected.tmdb_id}`
    : "search";
  return (
    <TmdbSearchPickerState
      key={targetKey}
      selected={selected}
      {...props}
    />
  );
}

function TmdbSearchPickerState({
  query,
  selected,
  onClear,
  onQueryChange,
  onSelect,
}: TmdbSearchPickerProps) {
  const [suggestions, setSuggestions] = useState<TmdbSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeServerId, setActiveServerId] = useState("");
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  const pickerRef = useRef<HTMLDivElement>(null);
  const suggestionsDismissedRef = useRef(false);
  const closeSuggestions = useCallback(() => {
    suggestionsDismissedRef.current = true;
    setSuggestions([]);
    setActiveSuggestion(-1);
  }, []);
  const availability = useQuery({
    queryKey: ["emby-availability", selected?.tmdb_id, selected?.media_type],
    queryFn: () =>
      checkEmbyAvailability(selected?.tmdb_id || 0, selected?.media_type || ""),
    enabled: Boolean(selected),
    staleTime: 60_000,
  });

  useEffect(() => {
    if (selected || query.trim().length < 3) {
      suggestionsDismissedRef.current = true;
      setSuggestions([]);
      setActiveSuggestion(-1);
      setLoading(false);
      setError("");
      return;
    }
    suggestionsDismissedRef.current = false;
    let active = true;
    const timeout = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const response = await searchTmdb(query.trim());
        if (active && !suggestionsDismissedRef.current) {
          setSuggestions(response.results || []);
          setActiveSuggestion(-1);
        }
      } catch (reason) {
        if (active) {
          setSuggestions([]);
          setActiveSuggestion(-1);
          setError(
            reason instanceof Error
              ? reason.message
              : "Ricerca TMDB non disponibile",
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }, 260);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [query, selected]);

  useEffect(() => {
    if (!suggestions.length) return undefined;

    function closeOnOutsidePointer(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !pickerRef.current?.contains(event.target)
      ) {
        closeSuggestions();
      }
    }

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () =>
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [closeSuggestions, suggestions.length]);

  if (selected) {
    const poster = tmdbPosterUrl(selected.poster_path);
    const availableOn = availability.data?.available_on || [];
    const activeServer = availableOn.find(
      (entry) => entry.server_id === activeServerId,
    );
    return (
      <div className="tmdb-selected-card">
        <div className="tmdb-selected-poster" aria-hidden="true">
          {poster ? (
            <img src={poster} alt="" />
          ) : selected.media_type === "tv" ? (
            <Tv size={22} />
          ) : (
            <Film size={22} />
          )}
        </div>
        <div className="tmdb-selected-copy">
          <strong>{selected.title}</strong>
          <span>
            {[selected.year, displayMediaType(selected.media_type)]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {selected.original_title &&
          selected.original_title !== selected.title ? (
            <small>Titolo originale: {selected.original_title}</small>
          ) : null}
          {availability.isLoading ? (
            <small className="tmdb-availability">
              <LoaderCircle size={13} className="animate-spin" /> Verifica
              disponibilità Emby...
            </small>
          ) : null}
          {availability.error ? (
            <p className="tmdb-availability tmdb-availability--error" role="alert">
              <span>
                Impossibile verificare su Emby: {availability.error.message}
              </span>
              <button
                type="button"
                onClick={() => void availability.refetch()}
                disabled={availability.isFetching}
              >
                Riprova
              </button>
            </p>
          ) : null}
          {availableOn.length ? (
            <div className="tmdb-availability">
              <span>Disponibile su</span>
              {availableOn.map((entry) => (
                <button
                  key={entry.server_id || entry.server_name}
                  type="button"
                  className={
                    entry.server_id === activeServerId ? "is-active" : ""
                  }
                  aria-pressed={entry.server_id === activeServerId}
                  onClick={() => setActiveServerId(entry.server_id || "")}
                >
                  {entry.server_name || entry.label || "Emby"}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Rimuovi titolo selezionato"
          aria-label="Rimuovi titolo selezionato"
          onClick={() => {
            setActiveServerId("");
            onClear();
          }}
        >
          <X size={17} aria-hidden="true" />
        </Button>
        {activeServer ? (
          <div className="tmdb-emby-browser">
            <EmbyMediaBrowser
              selected={selected}
              server={activeServer}
              onClose={() => setActiveServerId("")}
            />
          </div>
        ) : null}
      </div>
    );
  }

  function selectSuggestion(item: TmdbSearchResult) {
    setActiveServerId("");
    closeSuggestions();
    onSelect(item);
  }

  function handleSuggestionKeys(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!suggestions.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setActiveSuggestion((current) =>
        nextTmdbSuggestionIndex(
          current,
          event.key === "ArrowDown" ? 1 : -1,
          suggestions.length,
        ),
      );
      return;
    }
    if (event.key === "Enter" && activeSuggestion >= 0) {
      event.preventDefault();
      selectSuggestion(suggestions[activeSuggestion]);
    }
  }

  function closeWhenFocusLeaves(event: React.FocusEvent<HTMLDivElement>) {
    if (
      event.relatedTarget instanceof Node &&
      event.currentTarget.contains(event.relatedTarget)
    ) {
      return;
    }
    closeSuggestions();
  }

  function closeOnEscape(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape" || !suggestions.length) return;
    event.preventDefault();
    event.stopPropagation();
    closeSuggestions();
  }

  return (
    <div
      className="tmdb-picker"
      ref={pickerRef}
      onBlur={closeWhenFocusLeaves}
      onKeyDown={closeOnEscape}
    >
      <div className="research-search-input">
        <Search size={17} aria-hidden="true" />
        <input
          id="research-query"
          role="combobox"
          aria-autocomplete="list"
          aria-controls={suggestions.length ? "tmdb-suggestions" : undefined}
          aria-expanded={suggestions.length > 0}
          aria-activedescendant={
            activeSuggestion >= 0
              ? tmdbSuggestionDomId(
                  suggestions[activeSuggestion]?.media_type || "unknown",
                  suggestions[activeSuggestion]?.tmdb_id || 0,
                )
              : undefined
          }
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={handleSuggestionKeys}
          placeholder="Titolo, persona o keyword"
          autoComplete="off"
        />
        {loading ? (
          <LoaderCircle
            size={16}
            className="animate-spin"
            aria-label="Ricerca TMDB in corso"
          />
        ) : null}
      </div>
      {suggestions.length ? (
        <ul
          id="tmdb-suggestions"
          className="tmdb-suggestions"
          role="listbox"
          aria-label="Risultati TMDB"
        >
          {suggestions.map((item, index) => (
            <li key={`${item.media_type}-${item.tmdb_id}`}>
              <button
                id={tmdbSuggestionDomId(item.media_type, item.tmdb_id)}
                type="button"
                role="option"
                aria-selected={activeSuggestion === index}
                className={activeSuggestion === index ? "is-active" : ""}
                onMouseEnter={() => setActiveSuggestion(index)}
                onClick={() => selectSuggestion(item)}
              >
                {tmdbPosterUrl(item.poster_path) ? (
                  <img src={tmdbPosterUrl(item.poster_path) || ""} alt="" />
                ) : (
                  <span className="tmdb-suggestion-icon">
                    {item.media_type === "tv" ? (
                      <Tv size={16} />
                    ) : (
                      <Film size={16} />
                    )}
                  </span>
                )}
                <span>
                  <strong>{item.title}</strong>
                  <small>
                    {[
                      item.year,
                      displayMediaType(item.media_type),
                      `TMDB ${item.tmdb_id}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </span>
                <Check size={16} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p className="research-field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export { TmdbSearchPicker };
