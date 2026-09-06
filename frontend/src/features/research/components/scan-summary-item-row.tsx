import { ChevronDown, Play, Trash2 } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { SearchResultTable } from "@/features/research/components/search-result-table";
import type { RequestRuleTermField } from "@/features/research/request-search-rules";
import type { ScanSummaryItem } from "@/features/research/types";

function ScanSummaryItemRow({
  item,
  checked,
  qbittorrentAvailable,
  disabled,
  selectable = true,
  onToggle,
  onQuickSearch,
  onCleanup,
  onAddTerm,
}: {
  item: ScanSummaryItem;
  checked: boolean;
  qbittorrentAvailable: boolean;
  disabled: boolean;
  selectable?: boolean;
  onToggle: () => void;
  onQuickSearch: () => void;
  onCleanup: () => void;
  onAddTerm: (term: string, field: RequestRuleTermField) => Promise<string>;
}) {
  const [open, setOpen] = useState(false);
  const results = item.results || item.top_results || [];

  return <article className={item.is_stale ? "scan-summary-item is-stale" : "scan-summary-item"}>
    <header>
      {selectable ? <label><input type="checkbox" checked={checked} disabled={disabled} onChange={onToggle} aria-label={`Seleziona ${item.title || "richiesta"}`} /></label> : null}
      <button type="button" className="scan-summary-toggle" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
        <span>
          <strong>{item.title || "Titolo non disponibile"}{item.year ? ` (${item.year})` : ""}</strong>
          <small>{item.season !== null && item.season !== undefined ? `S${String(item.season).padStart(2, "0")} · ` : ""}{item.results_found || 0} risultati{item.is_stale ? " · storico" : ""}</small>
        </span>
        <ChevronDown size={17} className={open ? "is-open" : ""} aria-hidden="true" />
      </button>
      <div className="scan-summary-row-actions">
        <Button type="button" requiresWriteAccess variant="ghost" size="compact" disabled={disabled} onClick={onQuickSearch}><Play size={14} aria-hidden="true" /> Cerca</Button>
        <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Rimuovi dal riepilogo" aria-label="Rimuovi dal riepilogo" disabled={disabled} onClick={onCleanup}><Trash2 size={14} aria-hidden="true" /></Button>
      </div>
    </header>
    {open ? <div className="scan-summary-item-details">
      {item.queries?.length ? <details><summary>Query provate ({item.queries.length})</summary><ul>{item.queries.map((query, index) => <li key={`${query.query || "query"}-${index}`}>{query.query || "Query"} <span>{query.results_found || 0}</span></li>)}</ul></details> : null}
      {results.length ? <SearchResultTable results={results} qbittorrentAvailable={qbittorrentAvailable} onAddTerm={disabled ? undefined : onAddTerm} /> : <p>Nessun risultato accettato per questa richiesta.</p>}
      {item.excluded?.length ? <details><summary>Risultati esclusi ({item.excluded.length})</summary><ul>{item.excluded.map((excluded, index) => <li key={`${excluded.title || "result"}-${index}`}>{excluded.title || "Titolo"} · {excluded.reason || "escluso"}{excluded.indexer ? ` (${excluded.indexer})` : ""}</li>)}</ul></details> : null}
    </div> : null}
  </article>;
}

export { ScanSummaryItemRow };
