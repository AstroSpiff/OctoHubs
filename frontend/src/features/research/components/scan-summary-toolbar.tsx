import { ArrowDownUp } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import {
  changeScanSummarySort,
} from "@/features/research/scan-summary-sort";
import type {
  ScanSummarySort,
  ScanSummarySortKey,
} from "@/features/research/scan-summary-sort";

function ScanSummaryToolbar({
  sort,
  onChange,
}: {
  sort: ScanSummarySort;
  onChange: (sort: ScanSummarySort) => void;
}) {
  const directionLabel =
    sort.direction === "asc"
      ? "Ordine crescente: passa a decrescente"
      : "Ordine decrescente: passa a crescente";

  return (
    <div className="research-summary-toolbar">
      <label className="research-summary-sort">
        <span>Ordina</span>
        <select
          value={sort.key}
          aria-label="Ordina risultati richieste"
          onChange={(event) =>
            onChange(
              changeScanSummarySort(
                sort,
                event.target.value as ScanSummarySortKey,
              ),
            )
          }
        >
          <option value="default">Ordine ricerca</option>
          <option value="id">ID richiesta</option>
          <option value="title">Titolo</option>
          <option value="results">Numero risultati</option>
        </select>
      </label>
      {sort.key !== "default" ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title={directionLabel}
          aria-label={directionLabel}
          onClick={() => onChange(changeScanSummarySort(sort, sort.key))}
        >
          <ArrowDownUp size={15} aria-hidden="true" />
        </Button>
      ) : null}
    </div>
  );
}

export { ScanSummaryToolbar };
