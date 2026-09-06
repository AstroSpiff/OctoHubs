import type { MouseEvent as ReactMouseEvent } from "react";

import {
  SearchResultActions,
  type OpenTermMenuAction,
  type SearchResultActionNotice,
} from "@/features/research/components/search-result-actions";
import type { SearchResultEntry } from "@/features/research/search-result-groups";
import { displayFileSize } from "@/features/research/presentation";
import type { SearchResult } from "@/features/research/types";

type SearchResultRowProps = {
  result: SearchResult;
  selectable?: boolean;
  selected: boolean;
  selectedKeys: Set<string>;
  canSend: boolean;
  hasEpisodes: boolean;
  duplicates: SearchResultEntry[];
  onToggle: () => void;
  onToggleDuplicate: (key: string) => void;
  onNotice: (notice: SearchResultActionNotice) => void;
  onTitleContextMenu?: (event: ReactMouseEvent<HTMLElement>) => void;
  onOpenTermMenu?: OpenTermMenuAction;
  onLookupEmby?: (target: { title: string; year?: string | number }) => void;
};

function SearchResultRow({
  result,
  selectable = true,
  selected,
  selectedKeys,
  canSend,
  hasEpisodes,
  duplicates,
  onToggle,
  onToggleDuplicate,
  onNotice,
  onTitleContextMenu,
  onOpenTermMenu,
  onLookupEmby,
}: SearchResultRowProps) {
  return (
    <tr className={result.in_library ? "is-in-library" : undefined}>
      {selectable ? <td>
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          aria-label={`Seleziona ${result.title || "risultato"}`}
        />
      </td> : null}
      {hasEpisodes ? <td>{result.episode_code || "-"}</td> : null}
      <td>
        <strong
          className={onTitleContextMenu ? "research-result-title" : undefined}
          onContextMenu={onTitleContextMenu}
        >
          {result.title || "Titolo non disponibile"}
        </strong>
        {result.in_library ? <small>Già presente in libreria</small> : null}
        {result.season_label && !hasEpisodes ? (
          <small>{result.season_label}</small>
        ) : null}
        {duplicates.length ? (
          <DuplicateSources
            duplicates={duplicates}
            canSend={canSend}
            onNotice={onNotice}
            onTitleContextMenu={onTitleContextMenu}
            onOpenTermMenu={onOpenTermMenu}
            onLookupEmby={onLookupEmby}
            selectedKeys={selectedKeys}
            selectable={selectable}
            onToggle={onToggleDuplicate}
          />
        ) : null}
      </td>
      <td>{displayFileSize(result.size_gb)}</td>
      <td>
        {result.seeders || 0}
        {typeof result.leechers === "number" ? (
          <small> / {result.leechers}</small>
        ) : null}
      </td>
      <td>{result.indexer || "-"}</td>
      <td>
        <SearchResultActions
          result={result}
          canSend={canSend}
          onNotice={onNotice}
          onOpenTermMenu={onOpenTermMenu}
          onLookupEmby={onLookupEmby}
        />
      </td>
    </tr>
  );
}

type DuplicateSourcesProps = {
  duplicates: SearchResultEntry[];
  canSend: boolean;
  selectedKeys: Set<string>;
  selectable: boolean;
  onToggle: (key: string) => void;
  onNotice: (notice: SearchResultActionNotice) => void;
  onTitleContextMenu?: (event: ReactMouseEvent<HTMLElement>) => void;
  onOpenTermMenu?: OpenTermMenuAction;
  onLookupEmby?: (target: { title: string; year?: string | number }) => void;
};

function DuplicateSources({
  duplicates,
  canSend,
  selectedKeys,
  selectable,
  onToggle,
  onNotice,
  onTitleContextMenu,
  onOpenTermMenu,
  onLookupEmby,
}: DuplicateSourcesProps) {
  return (
    <details className="research-duplicate-sources">
      <summary>{duplicates.length} altre fonti</summary>
      <ul>
        {duplicates.map(({ key, result }) => (
          <li key={key}>
            {selectable ? <input
              type="checkbox"
              checked={selectedKeys.has(key)}
              onChange={() => onToggle(key)}
              aria-label={`Seleziona fonte ${result.title || "duplicata"}`}
            /> : null}
            <div className="research-duplicate-copy">
              <strong
                className={onTitleContextMenu ? "research-result-title" : undefined}
                onContextMenu={onTitleContextMenu}
              >
                {result.title || "Titolo non disponibile"}
              </strong>
              <small>{result.indexer || "Fonte non disponibile"}</small>
            </div>
            <SearchResultActions
              result={result}
              canSend={canSend}
              onNotice={onNotice}
              onOpenTermMenu={onOpenTermMenu}
              onLookupEmby={onLookupEmby}
            />
          </li>
        ))}
      </ul>
    </details>
  );
}

export { SearchResultRow };
