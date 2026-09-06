import { Eraser, Play, Trash2 } from "@/components/ui/icons";
import { useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { tabAtKey } from "@/components/ui/tab-navigation";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import {
  cleanupScanResults,
  runScan,
  saveRequestSearchRules,
  stopScan,
} from "@/features/research/api";
import { ScanSummaryItemRow } from "@/features/research/components/scan-summary-item-row";
import { ScanSummaryControls } from "@/features/research/components/scan-summary-controls";
import { ScanSummaryToolbar } from "@/features/research/components/scan-summary-toolbar";
import { defaultRequestRule } from "@/features/research/request-search-rules";
import type { RequestRuleTermField } from "@/features/research/request-search-rules";
import { createRequestRuleTermQueue } from "@/features/research/request-rule-term-queue";
import {
  scanSummaryItemKey,
  scanTargetForItem,
  scanTargetsFromItems,
} from "@/features/research/scan-summary-selection";
import {
  defaultScanSummarySort,
  sortScanSummaryItems,
} from "@/features/research/scan-summary-sort";
import type {
  ResearchOverview,
  ResearchNotice,
  ScanSummaryItem,
  ScanTarget,
} from "@/features/research/types";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";

type SummaryTab = "movie" | "tv";
const summaryTabs: SummaryTab[] = ["movie", "tv"];

function ScanSummaryWorkspace({
  overview,
  onRefresh,
}: {
  overview: ResearchOverview;
  onRefresh: () => void;
}) {
  const confirmation = useConfirmationDialog();
  const { canMutate } = useWorkspaceCapabilities();
  const [tab, setTab] = useState<SummaryTab>("movie");
  const [selectedItems, setSelectedItems] = useState<
    Map<string, ScanSummaryItem>
  >(new Map());
  const [notice, setNotice] = useState<ResearchNotice | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingRuleUpdates, setPendingRuleUpdates] = useState(0);
  const ruleQueue = useRef(
    createRequestRuleTermQueue(async (rule) => {
      await saveRequestSearchRules([rule]);
    }),
  );
  const [sort, setSort] = useState(defaultScanSummarySort);
  const scan = overview.scan;
  const items = overview.results.items || [];
  const movieItems = items.filter((item) => item.media_type !== "tv");
  const tvItems = items.filter((item) => item.media_type === "tv");
  const visibleItems = useMemo(
    () => sortScanSummaryItems(tab === "movie" ? movieItems : tvItems, sort),
    [movieItems, sort, tab, tvItems],
  );
  const selectedTargets = useMemo(
    () => scanTargetsFromItems(selectedItems.values()),
    [selectedItems],
  );

  function selectSummaryTab(next: SummaryTab) {
    setTab(next);
  }

  function selectSummaryTabFromKeyboard(
    event: KeyboardEvent<HTMLButtonElement>,
    current: SummaryTab,
  ) {
    const next = tabAtKey(summaryTabs, current, event.key);
    if (!next) return;
    event.preventDefault();
    selectSummaryTab(next);
    window.requestAnimationFrame(() => {
      document.getElementById(`research-summary-tab-${next}`)?.focus();
    });
  }

  function toggle(item: ScanSummaryItem) {
    const key = scanSummaryItemKey(item);
    setSelectedItems((current) => {
      const next = new Map(current);
      if (next.has(key)) next.delete(key);
      else next.set(key, item);
      return next;
    });
  }

  function selectVisibleItems() {
    setSelectedItems((current) => {
      const next = new Map(current);
      visibleItems.forEach((item) =>
        next.set(scanSummaryItemKey(item), item),
      );
      return next;
    });
  }

  function clearVisibleItems() {
    setSelectedItems((current) => {
      const next = new Map(current);
      visibleItems.forEach((item) => next.delete(scanSummaryItemKey(item)));
      return next;
    });
  }

  async function startScan(selected?: ScanTarget[]) {
    setBusy(true);
    setNotice(null);
    try {
      const response = await runScan(selected);
      setNotice({
        message: response.message || "Ricerca avviata.",
        tone: response.success ? "success" : "error",
      });
      if (response.success) setSelectedItems(new Map());
      onRefresh();
    } catch (reason) {
      setNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Avvio ricerca non riuscito.",
        tone: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  async function requestStop() {
    setBusy(true);
    try {
      const response = await stopScan();
      setNotice({
        message: response.message || "Ricerca interrotta.",
        tone: response.success ? "success" : "error",
      });
      onRefresh();
    } catch (reason) {
      setNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Stop ricerca non riuscito.",
        tone: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  async function cleanup(
    mode: "resolved" | "all" | "single",
    item?: ScanSummaryItem,
  ) {
    const question =
      mode === "all"
        ? "Cancellare tutto l'ultimo riepilogo? Lo storico delle ricerche manuali resterà disponibile."
        : mode === "resolved"
          ? "Rimuovere dal riepilogo le richieste già evase?"
          : "Rimuovere questo risultato dal riepilogo?";
    if (
      !(await confirmation.confirm({
        title:
          mode === "all"
            ? "Azzera riepilogo"
            : mode === "resolved"
              ? "Pulisci richieste evase"
              : "Rimuovi risultato",
        description: question,
        confirmLabel: mode === "all" ? "Azzera riepilogo" : "Conferma",
        tone: "danger",
      }))
    )
      return;
    setBusy(true);
    try {
      const response = await cleanupScanResults({
        mode,
        ...(item ? { request_id: item.request_id, season: item.season } : {}),
      });
      setNotice({
        message: response.removed
          ? `${response.message}: ${response.removed}`
          : response.message,
        tone: response.success ? "success" : "error",
      });
      onRefresh();
    } catch (reason) {
      setNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Pulizia risultati non riuscita.",
        tone: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  async function appendRuleTerm(
    item: ScanSummaryItem,
    term: string,
    field: RequestRuleTermField,
  ) {
    const request = overview.requests.find(
      (entry) =>
        String(entry.id ?? entry.request_id) === String(item.request_id),
    );
    if (!request)
      throw new Error(
        "La richiesta associata non è più disponibile. Aggiorna il riepilogo e riprova.",
      );
    const currentRule = defaultRequestRule(request, overview.search_rules);
    setPendingRuleUpdates((current) => current + 1);
    try {
      const message = await ruleQueue.current.enqueue(
        item.request_id,
        currentRule,
        term,
        field,
      );
      onRefresh();
      return message;
    } finally {
      setPendingRuleUpdates((current) => Math.max(0, current - 1));
    }
  }

  const interactionBusy = busy || pendingRuleUpdates > 0;

  return (
    <div className="research-summary-layout">
      <ScanSummaryControls scan={scan} hasConfig={overview.has_config} busy={interactionBusy} notice={notice} generatedAt={overview.results.generated_at} onStart={() => void startScan()} onStop={() => void requestStop()} onRefresh={onRefresh} />
      <section
        className="research-card research-scan-results"
        aria-labelledby="scan-summary-title"
      >
        <header className="research-card-heading">
          <div>
            <h3 id="scan-summary-title" className="contextual-heading" title="Ultimo riepilogo">Risultati delle richieste</h3>
            <p>
              {items.length
                ? `${items.length} richieste o stagioni nel riepilogo corrente.`
                : "Esegui una ricerca per generare risultati."}
            </p>
          </div>
          <div className="research-scan-actions">
            <Button
              type="button"
              requiresWriteAccess
              variant="ghost"
              size="compact"
              disabled={interactionBusy}
              onClick={() => void cleanup("resolved")}
            >
              <Eraser size={15} aria-hidden="true" /> Pulisci evasi
            </Button>
            <Button
              type="button"
              requiresWriteAccess
              variant="ghost"
              size="icon"
              title="Azzera ultimo riepilogo"
              aria-label="Azzera ultimo riepilogo"
              disabled={interactionBusy}
              onClick={() => void cleanup("all")}
            >
              <Trash2 size={15} aria-hidden="true" />
            </Button>
          </div>
        </header>
        {items.length ? (
          <>
            <div
              className="workspace-tabs workspace-tabs--context research-summary-tabs"
              role="tablist"
              aria-label="Tipi di risultati"
            >
              {summaryTabs.map((summaryTab) => (
                <button
                  key={summaryTab}
                  id={`research-summary-tab-${summaryTab}`}
                  type="button"
                  role="tab"
                  aria-selected={tab === summaryTab}
                  aria-controls={`research-summary-panel-${summaryTab}`}
                  tabIndex={tab === summaryTab ? 0 : -1}
                  className={tab === summaryTab ? "is-active" : ""}
                  onClick={() => selectSummaryTab(summaryTab)}
                  onKeyDown={(event) =>
                    selectSummaryTabFromKeyboard(event, summaryTab)
                  }
                >
                  {summaryTab === "movie" ? "Film" : "Serie TV"}
                  <span>
                    {summaryTab === "movie" ? movieItems.length : tvItems.length}
                  </span>
                </button>
              ))}
            </div>
            <div
              id={`research-summary-panel-${tab}`}
              role="tabpanel"
              aria-labelledby={`research-summary-tab-${tab}`}
              tabIndex={0}
            >
            <ScanSummaryToolbar sort={sort} onChange={setSort} />
            {canMutate ? <div className="research-scan-selection">
              <span>
                {selectedTargets.length
                  ? `${selectedTargets.length} selezionate`
                  : "Seleziona richieste o stagioni per una ricerca mirata."}
              </span>
              <div>
                <Button
                  type="button"
                  variant="ghost"
                  size="compact"
                  disabled={
                    interactionBusy || Boolean(scan.running) || !visibleItems.length
                  }
                  onClick={selectVisibleItems}
                >
                  Seleziona tutte
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="compact"
                  disabled={interactionBusy || !selectedItems.size}
                  onClick={clearVisibleItems}
                >
                  Deseleziona
                </Button>
                <Button
                  type="button"
                  requiresWriteAccess
                  variant="secondary"
                  size="compact"
                  disabled={!selectedTargets.length || interactionBusy || Boolean(scan.running)}
                  onClick={() => void startScan(selectedTargets)}
                >
                  <Play size={15} aria-hidden="true" /> Cerca selezionate
                </Button>
              </div>
            </div> : null}
            <div className="scan-summary-list">
              {visibleItems.map((item) => (
                <ScanSummaryItemRow
                  key={scanSummaryItemKey(item)}
                  item={item}
                  checked={selectedItems.has(scanSummaryItemKey(item))}
                  selectable={canMutate}
                  qbittorrentAvailable={overview.qbittorrent_available}
                  disabled={interactionBusy || Boolean(scan.running)}
                  onToggle={() => toggle(item)}
                  onQuickSearch={() => void startScan([scanTargetForItem(item)])}
                  onCleanup={() => void cleanup("single", item)}
                  onAddTerm={(term, field) => appendRuleTerm(item, term, field)}
                />
              ))}
            </div>
            </div>
          </>
        ) : (
          <div className="research-empty-state">
            Nessun risultato disponibile.
          </div>
        )}
      </section>
      {confirmation.dialog}
    </div>
  );
}

export { ScanSummaryWorkspace };
