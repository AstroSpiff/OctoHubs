import { RefreshCw, Search } from "@/components/ui/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { useNavigationPreferencesContext } from "@/features/navigation/use-navigation-preferences-context";
import { GlobalSearchRules } from "@/features/research/components/global-search-rules";
import { IndependentSearchWorkspace } from "@/features/research/components/independent-search-workspace";
import { JellyseerrRequestsWorkspace } from "@/features/research/components/jellyseerr-requests-workspace";
import { ResearchTabs } from "@/features/research/components/research-tabs";
import { ScanSummaryWorkspace } from "@/features/research/components/scan-summary-workspace";
import { manualSearchFromQuery } from "@/features/research/manual-search-query";
import { researchTabFromRoute } from "@/features/research/research-navigation";
import { researchTabPresentation } from "@/features/research/research-tab-presentation";
import { useResearchOverview } from "@/features/research/use-research-overview";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";

function ResearchPage() {
  const overview = useResearchOverview();
  const { refetch } = overview;
  const { search } = useLocation();
  const { tab: routeTab } = useParams();
  const tab = researchTabFromRoute(routeTab);
  const previousTabRef = useRef(tab);
  const confirmation = useConfirmationDialog();
  const navigationPreferences = useNavigationPreferencesContext();
  const [drafts, setDrafts] = useState({ globalRules: false, requestRules: false });
  const initialSearch = useMemo(() => manualSearchFromQuery(search), [search]);
  const hasUnsavedChanges = drafts.globalRules || drafts.requestRules;
  const refreshOverview = useCallback(() => {
    void refetch();
  }, [refetch]);
  const updateDraft = useCallback(
    (scope: "globalRules" | "requestRules", dirty: boolean) => {
      setDrafts((current) =>
        current[scope] === dirty ? current : { ...current, [scope]: dirty },
      );
    },
    [],
  );
  const updateGlobalRulesDirty = useCallback(
    (dirty: boolean) => updateDraft("globalRules", dirty),
    [updateDraft],
  );
  const updateRequestRulesDirty = useCallback(
    (dirty: boolean) => updateDraft("requestRules", dirty),
    [updateDraft],
  );

  useEffect(() => {
    if (previousTabRef.current === tab) return;
    previousTabRef.current = tab;
    setDrafts({ globalRules: false, requestRules: false });
  }, [tab]);

  useBeforeUnloadWarning(hasUnsavedChanges);
  useUnsavedChangesNavigationGuard(hasUnsavedChanges, confirmation.confirm);

  return (
    <WorkspacePage className="research-page">
      <WorkspaceHeading
        context="Jellyseerr e indexer"
        title="Ricerca e richieste"
        description="Ricerca manuale, monitoraggio richieste e riepiloghi con dati coerenti in tempo reale."
        actions={(
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Aggiorna dati ricerca"
            aria-label="Aggiorna dati ricerca"
            onClick={refreshOverview}
            disabled={overview.isFetching}
          >
            <RefreshCw size={16} className={overview.isFetching ? "animate-spin" : ""} aria-hidden="true" />
          </Button>
        )}
      />
      {!overview.data && overview.isLoading ? <div className="loading-state">Caricamento ricerca e richieste...</div> : null}
      {!overview.data && overview.error ? <div className="inline-alert inline-alert--error" role="alert">{overview.error.message}</div> : null}
      {overview.data ? (
        <ResearchTabs active={tab} variant={navigationPreferences.preferences.secondary_navigation}>
          <WorkspaceHeading level="section" {...researchTabPresentation(tab)} />
          {overview.isLoading ? <div className="loading-state">Aggiornamento ricerca e richieste...</div> : null}
          {overview.error ? <div className="inline-alert inline-alert--error" role="alert">{overview.error.message}</div> : null}
          {!overview.data.has_config ? (
            <div className="inline-alert inline-alert--error" role="alert">
              <Search size={17} aria-hidden="true" />
              Configurazione incompleta: collega i servizi necessari prima di avviare le ricerche.
            </div>
          ) : null}
          {tab === "independent" ? <IndependentSearchWorkspace overview={overview.data} initialSearch={initialSearch} /> : null}
          {tab === "summary" ? <ScanSummaryWorkspace overview={overview.data} onRefresh={refreshOverview} /> : null}
          {tab === "rules" ? <GlobalSearchRules overview={overview.data} onSaved={refreshOverview} onDirtyChange={updateGlobalRulesDirty} /> : null}
          {tab === "requests" ? <JellyseerrRequestsWorkspace overview={overview.data} onRefresh={refreshOverview} onDirtyChange={updateRequestRulesDirty} /> : null}
        </ResearchTabs>
      ) : null}
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { ResearchPage };
