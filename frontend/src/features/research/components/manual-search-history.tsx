import {
  Eye,
  History,
  LoaderCircle,
  Pencil,
  RotateCcw,
  Trash2,
} from "@/components/ui/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import {
  deleteManualSearch,
  getManualSearchHistory,
} from "@/features/research/api";
import { manualSearchInputFromHistory } from "@/features/research/manual-search-history";
import { WriteAction } from "@/features/session/workspace-capabilities";
import {
  displayMediaType,
  formatResearchDate,
} from "@/features/research/presentation";
import type {
  SearchResult,
  StreamingSearchInput,
} from "@/features/research/types";

function ManualSearchHistory({
  refreshToken,
  searching,
  onView,
  onEdit,
  onRepeat,
}: {
  refreshToken: number;
  searching: boolean;
  onView: (results: SearchResult[]) => void;
  onEdit: (input: StreamingSearchInput) => void;
  onRepeat: (input: StreamingSearchInput) => Promise<void>;
}) {
  const confirmation = useConfirmationDialog();
  const client = useQueryClient();
  const [repeatingId, setRepeatingId] = useState<number | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [failedRemovalId, setFailedRemovalId] = useState<number | null>(null);
  const history = useQuery({
    queryKey: ["manual-search-history", refreshToken],
    queryFn: getManualSearchHistory,
    staleTime: 10_000,
  });
  const remove = useMutation({
    mutationFn: deleteManualSearch,
    onSuccess: () => client.invalidateQueries({ queryKey: ["manual-search-history"] }),
    onError: (_error, searchId) => setFailedRemovalId(searchId),
    onSettled: () => setRemovingId(null),
  });
  const entries = history.data?.searches || [];
  const actionsDisabled = searching || repeatingId !== null || remove.isPending;

  async function repeat(entry: (typeof entries)[number]) {
    const input = manualSearchInputFromHistory(entry);
    if (!input) return;
    setRepeatingId(entry.id);
    try {
      await onRepeat(input);
    } catch {
      // Il workspace espone l'errore della ricerca in un punto visibile.
    } finally {
      setRepeatingId(null);
    }
  }

  async function removeEntry(searchId: number) {
    if (
      !(await confirmation.confirm({
        title: "Elimina ricerca dallo storico",
        description: "Eliminare questa ricerca e i relativi risultati salvati?",
        confirmLabel: "Elimina ricerca",
        tone: "danger",
      }))
    )
      return;
    remove.reset();
    setFailedRemovalId(null);
    setRemovingId(searchId);
    remove.mutate(searchId);
  }

  return (
    <section
      className="research-card research-history-card"
      aria-labelledby="manual-search-history-title"
    >
      <header className="research-card-heading">
        <div>
          <h3 id="manual-search-history-title" className="contextual-heading" title="Archivio">Storico ricerche</h3>
          <p>
            Riapri i risultati completi di una ricerca manuale senza
            rilanciarla.
          </p>
        </div>
        <History size={22} aria-hidden="true" />
      </header>
      {history.isLoading ? (
        <div className="research-empty-state">
          <LoaderCircle size={18} className="animate-spin" aria-hidden="true" />{" "}
          Caricamento storico...
        </div>
      ) : null}
      {history.error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {history.error.message}
        </div>
      ) : null}
      {remove.error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          Eliminazione della ricerca {failedRemovalId !== null ? `#${failedRemovalId} ` : ""}non riuscita: {remove.error.message}
        </div>
      ) : null}
      {!history.isLoading && !history.error && !entries.length ? (
        <div className="research-empty-state">
          Nessuna ricerca manuale salvata.
        </div>
      ) : null}
      {entries.length ? (
        <ul className="manual-search-history-list">
          {entries.map((entry) => {
            const first = entry.items?.[0];
            const results = first?.results || [];
            const input = manualSearchInputFromHistory(entry);
            const repeating = repeatingId === entry.id;
            const removing = removingId === entry.id;
            return (
              <li key={entry.id}>
                <div>
                  <strong>
                    {first?.title ||
                      entry.search_context?.query ||
                      "Ricerca senza titolo"}
                  </strong>
                  <span>
                    {[
                      displayMediaType(
                        first?.media_type || entry.search_context?.media_type,
                      ),
                      `${first?.results_found ?? results.length} risultati`,
                      formatResearchDate(entry.generated_at),
                    ].join(" · ")}
                  </span>
                </div>
                <div className="manual-search-history-actions">
                  <Button
                    type="button"
                    variant="ghost"
                    size="compact"
                    title="Visualizza risultati"
                    onClick={() => onView(results)}
                    disabled={actionsDisabled}
                  >
                    <Eye size={15} aria-hidden="true" /> Apri
                  </Button>
                  <WriteAction>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      title="Modifica ricerca"
                      aria-label="Modifica ricerca"
                      disabled={!input || actionsDisabled}
                      onClick={() => input && onEdit(input)}
                    >
                      <Pencil size={15} aria-hidden="true" />
                    </Button>
                  </WriteAction>
                  <Button
                    type="button"
                    requiresWriteAccess
                    variant="ghost"
                    size="icon"
                    title="Ripeti ricerca"
                    aria-label="Ripeti ricerca"
                    disabled={!input || actionsDisabled}
                    onClick={() => void repeat(entry)}
                  >
                    {repeating ? (
                      <LoaderCircle
                        size={15}
                        className="animate-spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <RotateCcw size={15} aria-hidden="true" />
                    )}
                  </Button>
                  <Button
                    type="button"
                    requiresWriteAccess
                    variant="ghost"
                    size="icon"
                    title="Elimina dallo storico"
                    aria-label="Elimina dallo storico"
                    disabled={actionsDisabled}
                    onClick={() => void removeEntry(entry.id)}
                  >
                    {removing ? (
                      <LoaderCircle
                        size={15}
                        className="animate-spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <Trash2 size={15} aria-hidden="true" />
                    )}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
      {confirmation.dialog}
    </section>
  );
}

export { ManualSearchHistory };
