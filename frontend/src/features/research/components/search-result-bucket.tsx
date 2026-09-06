import {
  CheckSquare,
  Square,
} from "@/components/ui/icons";
import { type MouseEvent as ReactMouseEvent, useMemo, useState } from "react";

import type {
  OpenTermMenuAction,
  SearchResultActionNotice,
} from "@/features/research/components/search-result-actions";
import { SearchResultRow } from "@/features/research/components/search-result-rows";
import { filterBucketResults } from "@/features/research/search-result-groups";
import type {
  SearchResultBucket,
} from "@/features/research/search-result-groups";

type SearchResultBucketProps = {
  bucket: SearchResultBucket;
  selectable?: boolean;
  canSend: boolean;
  selected: Set<string>;
  onNotice: (notice: SearchResultActionNotice) => void;
  onToggle: (key: string) => void;
  onToggleItems: (keys: string[], selected: boolean) => void;
  onTitleContextMenu?: (event: ReactMouseEvent<HTMLElement>) => void;
  onOpenTermMenu?: OpenTermMenuAction;
  onLookupEmby?: (target: { title: string; year?: string | number }) => void;
};

function SearchResultBucket({
  bucket,
  selectable = true,
  canSend,
  selected,
  onNotice,
  onToggle,
  onToggleItems,
  onTitleContextMenu,
  onOpenTermMenu,
  onLookupEmby,
}: SearchResultBucketProps) {
  const [filter, setFilter] = useState("");
  const visibleItems = useMemo(
    () => filterBucketResults(bucket.items, filter),
    [bucket.items, filter],
  );
  const visibleKeys = visibleItems.flatMap((item) => [
    item.key,
    ...item.duplicates.map((duplicate) => duplicate.key),
  ]);
  const allVisibleSelected =
    visibleKeys.length > 0 &&
    visibleKeys.every((key) => selected.has(key));
  const hasEpisodes = bucket.items.some(({ result }) =>
    Boolean(result.episode_code),
  );
  const sourceCount = bucket.items.reduce(
    (count, item) => count + item.duplicates.length + 1,
    0,
  );

  return (
    <section
      className="research-result-bucket"
      aria-labelledby={`result-bucket-${bucket.key}`}
    >
      <header className="research-result-bucket-heading">
        <div>
          <h3 id={`result-bucket-${bucket.key}`}>
            {bucket.label} <span>{bucket.items.length}</span>
          </h3>
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filtra termini"
            aria-label={`Filtra ${bucket.label}`}
          />
        </div>
        <small>
          {filter
            ? `${visibleItems.length} di ${bucket.items.length} risultati`
            : `${bucket.items.length} risultati`}
          {sourceCount > bucket.items.length ? ` · ${sourceCount} fonti` : ""}
        </small>
      </header>
      <div
        className="research-results-table-wrap"
        role="region"
        tabIndex={0}
        aria-label="Risultati di ricerca. Scorri orizzontalmente per vedere tutte le colonne."
      >
        <table className="research-results-table">
          <thead>
            <tr>
              {selectable ? <th scope="col">
                <button
                  type="button"
                  className="research-select-all"
                  onClick={() =>
                    onToggleItems(visibleKeys, !allVisibleSelected)
                  }
                  aria-label={
                    allVisibleSelected
                      ? `Deseleziona ${bucket.label}`
                      : `Seleziona ${bucket.label}`
                  }
                >
                  {allVisibleSelected ? (
                    <CheckSquare size={17} aria-hidden="true" />
                  ) : (
                    <Square size={17} aria-hidden="true" />
                  )}
                </button>
              </th> : null}
              {hasEpisodes ? <th scope="col">Ep.</th> : null}
              <th scope="col">Titolo</th>
              <th scope="col">Dimensione</th>
              <th scope="col">Seed</th>
              <th scope="col">Indexer</th>
              <th scope="col">
                <span className="sr-only">Azioni</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visibleItems.map(({ key, result, duplicates }) => (
              <SearchResultRow
                key={`${result.guid || result.title || "result"}-${key}`}
                result={result}
                selectable={selectable}
                selected={selected.has(key)}
                selectedKeys={selected}
                canSend={canSend}
                hasEpisodes={hasEpisodes}
                duplicates={duplicates}
                onToggle={() => onToggle(key)}
                onToggleDuplicate={onToggle}
                onNotice={onNotice}
                onTitleContextMenu={onTitleContextMenu}
                onOpenTermMenu={onOpenTermMenu}
                onLookupEmby={onLookupEmby}
              />
            ))}
            {!visibleItems.length ? (
              <tr>
                <td
                  className="research-empty-table-row"
                  colSpan={hasEpisodes ? (selectable ? 7 : 6) : selectable ? 6 : 5}
                >
                  Nessun risultato con questi termini.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export { SearchResultBucket };
