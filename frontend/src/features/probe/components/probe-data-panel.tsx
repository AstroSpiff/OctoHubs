import { Download, RefreshCw } from "@/components/ui/icons";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  ProbeBlacklistPanel,
  ProbeHistoryPanel,
  ProbeQueuePanel,
} from "@/features/probe/components/probe-data-list-panels";
import { ProbeDataTabs } from "@/features/probe/components/probe-data-tabs";
import { probeDataTabOptions } from "@/features/probe/probe-data-tab-options";
import type { ProbeDataTab } from "@/features/probe/probe-data-tab-options";
import {
  probeItemHasIssue,
  probeScopeLabel,
} from "@/features/probe/presentation";
import type {
  ProbeBlacklistItem,
  ProbeHistoryItem,
  ProbeQueueItem,
  ProbeScope,
} from "@/features/probe/types";

type DataPanelProps = {
  scope: ProbeScope;
  queue: ProbeQueueItem[];
  queueLoaded: boolean;
  history: ProbeHistoryItem[];
  historyLoaded: boolean;
  errors: ProbeBlacklistItem[];
  errorsLoaded: boolean;
  incomplete: ProbeBlacklistItem[];
  incompleteLoaded: boolean;
  serverNames: Record<string, string>;
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  busy: boolean;
  downloadUrl?: string;
  settings?: ReactNode;
  onRefresh: () => void;
  onLoadMore: () => void;
  onActiveTabChange: (tab: ProbeDataTab) => void;
  onClearQueue: () => void;
  onClearHistory: () => void;
  onClearBlacklist: (type: "error" | "incomplete") => void;
  onRemoveQueue: (item: ProbeQueueItem) => void;
  onRemoveBlacklist: (
    type: "error" | "incomplete",
    item: ProbeBlacklistItem,
  ) => void;
  onRetryHistory: (item: ProbeHistoryItem) => void;
  onRetryBlacklist: (
    type: "error" | "incomplete",
    item: ProbeBlacklistItem,
  ) => void;
  onRetryMany: (items: Array<ProbeHistoryItem | ProbeBlacklistItem>) => void;
  retryProgress?: { completed: number; total: number } | null;
  onBeforeTabChange?: () => boolean | Promise<boolean>;
};

function ProbeDataPanel({
  scope,
  queue,
  queueLoaded,
  history,
  historyLoaded,
  errors,
  errorsLoaded,
  incomplete,
  incompleteLoaded,
  serverNames,
  loading,
  hasMore,
  loadingMore,
  busy,
  downloadUrl,
  settings,
  onRefresh,
  onLoadMore,
  onActiveTabChange,
  onClearQueue,
  onClearHistory,
  onClearBlacklist,
  onRemoveQueue,
  onRemoveBlacklist,
  onRetryHistory,
  onRetryBlacklist,
  onRetryMany,
  retryProgress,
  onBeforeTabChange,
}: DataPanelProps) {
  const [tab, setTab] = useState<ProbeDataTab>("queue");
  const [issuesOnly, setIssuesOnly] = useState(false);
  const visibleHistory = useMemo(
    () => (issuesOnly ? history.filter(probeItemHasIssue) : history),
    [history, issuesOnly],
  );
  const issueItems = useMemo(
    () => history.filter(probeItemHasIssue),
    [history],
  );
  const label = probeScopeLabel(scope);
  useEffect(() => {
    setTab("queue");
    setIssuesOnly(false);
    onActiveTabChange("queue");
  }, [onActiveTabChange, scope]);

  const tabs = probeDataTabOptions({
    queueCount: queueLoaded ? queue.length : undefined,
    historyCount: historyLoaded ? history.length : undefined,
    errorCount: errorsLoaded ? errors.length : undefined,
    incompleteCount: incompleteLoaded ? incomplete.length : undefined,
    showSettings: Boolean(settings),
  });

  async function selectTab(nextTab: ProbeDataTab) {
    if (nextTab === tab) return true;
    if (
      tab === "settings" &&
      onBeforeTabChange &&
      !(await onBeforeTabChange())
    ) {
      return false;
    }
    setTab(nextTab);
    onActiveTabChange(nextTab);
    return true;
  }

  return (
    <section className="probe-data-panel" aria-labelledby="probe-data-title">
      <header>
        <div>
          <h3 id="probe-data-title" className="contextual-heading" title={`Dati ${label}`}>Coda, storico e anomalie</h3>
        </div>
        <span className="probe-data-header-actions">
          {downloadUrl ? (
            <Button
              asChild
              variant="ghost"
              size="compact"
              title="Esporta errori e incompleti in CSV"
            >
              <a href={downloadUrl}>
                <Download size={15} aria-hidden="true" />
                Esporta CSV
              </a>
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Aggiorna dati"
            aria-label="Aggiorna dati"
            onClick={onRefresh}
            disabled={loading || busy}
          >
            <RefreshCw
              size={16}
              className={loading ? "animate-spin" : ""}
              aria-hidden="true"
            />
          </Button>
        </span>
      </header>
      <ProbeDataTabs value={tab} tabs={tabs} onChange={selectTab} />
      <div
        id={`probe-data-panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`probe-data-tab-${tab}`}
        tabIndex={0}
      >
      {tab === "queue" ? (
        <ProbeQueuePanel
          items={queue}
          serverNames={serverNames}
          busy={busy}
          onClear={onClearQueue}
          onRemove={onRemoveQueue}
        />
      ) : null}
      {tab === "history" ? (
        <ProbeHistoryPanel
          items={visibleHistory}
          totalCount={history.length}
          serverNames={serverNames}
          issuesOnly={issuesOnly}
          hasIssues={issueItems.length > 0}
          busy={busy}
          onIssuesOnly={setIssuesOnly}
          onClear={onClearHistory}
          onRetry={onRetryHistory}
          onRetryMany={() => onRetryMany(issueItems)}
          retryProgress={retryProgress}
        />
      ) : null}
      {tab === "errors" ? (
        <ProbeBlacklistPanel
          title="Errori dopo tre tentativi"
          description="Questi file non vengono più elaborati automaticamente. Rimuovili o riprovali per renderli di nuovo eleggibili."
          items={errors}
          serverNames={serverNames}
          type="error"
          busy={busy}
          onClear={onClearBlacklist}
          onRemove={onRemoveBlacklist}
          onRetry={onRetryBlacklist}
        />
      ) : null}
      {tab === "incomplete" ? (
        <ProbeBlacklistPanel
          title="Metadata incompleti dopo tre tentativi"
          description="La probe è terminata senza scrivere i mediainfo. Rimuovi o riprova questi elementi per inserirli di nuovo nel flusso."
          items={incomplete}
          serverNames={serverNames}
          type="incomplete"
          busy={busy}
          onClear={onClearBlacklist}
          onRemove={onRemoveBlacklist}
          onRetry={onRetryBlacklist}
        />
      ) : null}
      {tab === "settings" ? settings : null}
      {tab !== "settings" && hasMore ? (
        <div className="probe-data-pagination">
          <Button
            type="button"
            variant="secondary"
            size="compact"
            onClick={onLoadMore}
            disabled={loadingMore || busy}
          >
            {loadingMore ? "Caricamento..." : "Carica altri risultati"}
          </Button>
        </div>
      ) : null}
      </div>
    </section>
  );
}

export { ProbeDataPanel };
