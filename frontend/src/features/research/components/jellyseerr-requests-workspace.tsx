import { Check, ChevronDown, LoaderCircle, RefreshCw, RotateCcw } from "@/components/ui/icons";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { tabAtKey } from "@/components/ui/tab-navigation";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WriteAction } from "@/features/session/workspace-capabilities";
import {
  getJellyseerrRefreshStatus,
  refreshJellyseerrRequests,
  saveRequestSearchRules,
} from "@/features/research/api";
import { RequestRuleCard } from "@/features/research/components/request-rule-card";
import { formatResearchDate } from "@/features/research/presentation";
import {
  defaultRequestRule,
  requestKey,
  rulesFromRequests,
} from "@/features/research/request-search-rules";
import { shouldScheduleRequestRulesAutosave } from "@/features/research/request-rules-autosave";
import type {
  RequestSearchRule,
  ResearchOverview,
  ResearchNotice,
} from "@/features/research/types";

type RequestTab = "movie" | "tv";

const requestTabs: RequestTab[] = ["movie", "tv"];

function JellyseerrRequestsWorkspace({
  overview,
  onRefresh,
  onDirtyChange,
}: {
  overview: ResearchOverview;
  onRefresh: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const confirmation = useConfirmationDialog();
  const sourceRequests = overview.all_requests || overview.requests;
  const sourceSignature = useMemo(
    () => JSON.stringify([
      overview.search_rules,
      sourceRequests.map((request) => [request.id ?? request.request_id, request.rules]),
    ]),
    [overview.search_rules, sourceRequests],
  );
  const [tab, setTab] = useState<RequestTab>("movie");
  const [drafts, setDrafts] = useState<Record<string, RequestSearchRule>>(() =>
    rulesFromRequests(sourceRequests, overview.search_rules),
  );
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<ResearchNotice | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveRevision, setSaveRevision] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [hideAvailable, setHideAvailable] = useState(true);
  const [expandedLists, setExpandedLists] = useState<Record<RequestTab, boolean>>({
    movie: true,
    tv: true,
  });
  const draftRef = useRef(drafts);
  const lastAttemptedSaveRevision = useRef(0);
  const refreshStatus = useQuery({
    queryKey: ["jellyseerr-requests-refresh"],
    queryFn: getJellyseerrRefreshStatus,
    enabled: refreshing,
    refetchInterval: refreshing ? 2_500 : false,
  });
  const movieRequests = overview.all_movie_requests || overview.movie_requests;
  const tvRequests = overview.all_tv_requests || overview.tv_requests;
  const tabRequests = tab === "movie" ? movieRequests : tvRequests;
  const visibleRequests = hideAvailable ? tabRequests.filter((request) => !request.is_available) : tabRequests;
  const availableCount = tabRequests.filter((request) => request.is_available).length;
  const pendingCount = tabRequests.length - availableCount;
  const listExpanded = expandedLists[tab];
  const visibleCountLabel = hideAvailable ? `${visibleRequests.length} da gestire su ${tabRequests.length}` : `${tabRequests.length} richieste totali`;

  draftRef.current = drafts;

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(
    () => () => onDirtyChange?.(false),
    [onDirtyChange],
  );

  useEffect(() => {
    if (!dirty) setDrafts(rulesFromRequests(sourceRequests, overview.search_rules));
  }, [overview.search_rules, dirty, sourceRequests, sourceSignature]);

  useEffect(() => {
    if (!shouldScheduleRequestRulesAutosave({
      dirty,
      saving,
      revision: saveRevision,
      lastAttemptedRevision: lastAttemptedSaveRevision.current,
    })) return;
    const timeout = window.setTimeout(async () => {
      lastAttemptedSaveRevision.current = saveRevision;
      setSaving(true);
      setNotice(null);
      setSaveError(null);
      try {
        const submittedDrafts = draftRef.current;
        const response = await saveRequestSearchRules(Object.values(submittedDrafts));
        if (!response.success) {
          throw new Error(response.message || "Salvataggio regole richieste non riuscito.");
        }
        const savedDraftsAreCurrent = JSON.stringify(draftRef.current) === JSON.stringify(submittedDrafts);
        if (savedDraftsAreCurrent) setDirty(false);
        setNotice({ message: response.message || "Regole per le richieste aggiornate.", tone: "success" });
        onRefresh();
      } catch (reason) {
        setSaveError(reason instanceof Error ? reason.message : "Salvataggio regole richieste non riuscito.");
      } finally {
        setSaving(false);
      }
    }, 650);
    return () => window.clearTimeout(timeout);
  }, [dirty, onRefresh, saveRevision, saving]);

  useEffect(() => {
    if (!refreshing || refreshStatus.isFetching || refreshStatus.data?.running) return;
    setRefreshing(false);
    const message = refreshStatus.data?.last_error || refreshStatus.data?.last_warning || "Lista richieste aggiornata.";
    setNotice({
      message,
      tone: refreshStatus.data?.last_error ? "error" : refreshStatus.data?.last_warning ? "warning" : "success",
    });
    onRefresh();
  }, [onRefresh, refreshStatus.data, refreshStatus.isFetching, refreshing]);

  function selectRequestTabFromKeyboard(event: KeyboardEvent<HTMLButtonElement>, current: RequestTab) {
    const next = tabAtKey(requestTabs, current, event.key);
    if (!next) return;
    event.preventDefault();
    setTab(next);
    window.requestAnimationFrame(() => document.getElementById(`research-request-tab-${next}`)?.focus());
  }

  function updateRule(requestId: string, patch: Partial<RequestSearchRule>) {
    setDrafts((current) => ({ ...current, [requestId]: { ...current[requestId], ...patch } }));
    setDirty(true);
    setSaveError(null);
    setSaveRevision((current) => current + 1);
  }

  function setAllEnabled(enabled: boolean) {
    setDrafts((current) => {
      const next = { ...current };
      visibleRequests.forEach((request) => {
        const key = requestKey(request);
        next[key] = { ...(next[key] || defaultRequestRule(request, overview.search_rules)), enabled };
      });
      return next;
    });
    setDirty(true);
    setSaveError(null);
    setSaveRevision((current) => current + 1);
  }

  async function resetVisibleRules() {
    if (!await confirmation.confirm({
      title: "Ripristina regole richieste",
      description: "Ripristinare termini e opzioni di tutte le richieste visibili ai valori globali?",
      confirmLabel: "Ripristina regole",
      tone: "danger",
    })) return;
    setDrafts((current) => {
      const next = { ...current };
      visibleRequests.forEach((request) => {
        next[requestKey(request)] = defaultRequestRule(request, overview.search_rules);
      });
      return next;
    });
    setDirty(true);
    setSaveError(null);
    setSaveRevision((current) => current + 1);
  }

  async function refreshRequests() {
    setRefreshing(true);
    setNotice(null);
    try {
      const response = await refreshJellyseerrRequests();
      if (!response.success) {
        setRefreshing(false);
        setNotice({
          message: response.message || "Aggiornamento richieste non riuscito.",
          tone: "error",
        });
        return;
      }
      setNotice({ message: response.message || "Aggiornamento richieste avviato.", tone: response.success ? "success" : "error" });
    } catch (reason) {
      setRefreshing(false);
      setNotice({ message: reason instanceof Error ? reason.message : "Aggiornamento richieste non riuscito.", tone: "error" });
    }
  }

  return <section id="requests-refresh" className="research-card research-requests-card" aria-labelledby="jellyseerr-requests-title" tabIndex={-1}>
    <header className="research-card-heading">
      <div>
        <h3 id="jellyseerr-requests-title" className="contextual-heading" title="Jellyseerr">Sincronizzazione Jellyseerr</h3>
        <p>{overview.requests_updated_at ? `Ultimo aggiornamento: ${formatResearchDate(overview.requests_updated_at)}` : "Nessun dato in cache: aggiorna la lista per leggere Jellyseerr."}</p>
      </div>
      <Button type="button" requiresWriteAccess variant="secondary" size="compact" disabled={!overview.has_config || refreshing} onClick={() => void refreshRequests()}>
        {refreshing ? <LoaderCircle size={15} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={15} aria-hidden="true" />}
        Aggiorna lista
      </Button>
    </header>
    {overview.requests_refresh_warning ? <div className="research-request-warning">{overview.requests_refresh_warning}{overview.requests_refresh_warning_at ? ` (${formatResearchDate(overview.requests_refresh_warning_at)})` : ""}</div> : null}
    {saveError ? <div className="inline-alert inline-alert--error" role="alert"><span>{saveError}</span><Button type="button" requiresWriteAccess variant="ghost" size="compact" disabled={saving} onClick={() => { setSaveError(null); setSaveRevision((current) => current + 1); }}>Riprova</Button></div> : null}
    {notice ? <div className={`inline-alert inline-alert--${notice.tone}`} role={notice.tone === "error" ? "alert" : "status"}>{notice.tone === "success" ? <Check size={16} aria-hidden="true" /> : null}{notice.message}</div> : null}
    {saving ? <div className="research-save-state"><LoaderCircle size={14} className="animate-spin" aria-hidden="true" />Salvataggio regole richieste...</div> : null}
    {!overview.has_config ? (
      <div className="research-empty-state research-request-configuration-needed">
        <p>
          Configura Jellyseerr e gli altri servizi necessari prima di leggere
          le richieste monitorate.
        </p>
        <Button asChild type="button" variant="ghost" size="compact">
          <Link to="/configuration?focus=configuration-connections#services">Apri configurazione servizi</Link>
        </Button>
      </div>
    ) : tabRequests.length ? <>
      <div className="workspace-tabs workspace-tabs--context research-summary-tabs research-request-tabs" role="tablist" aria-label="Tipi richieste">
        {requestTabs.map((requestTab) => <button key={requestTab} id={`research-request-tab-${requestTab}`} type="button" role="tab" aria-selected={tab === requestTab} aria-controls={`research-request-panel-${requestTab}`} tabIndex={tab === requestTab ? 0 : -1} className={tab === requestTab ? "is-active" : ""} onClick={() => setTab(requestTab)} onKeyDown={(event) => selectRequestTabFromKeyboard(event, requestTab)}>
          {requestTab === "movie" ? "Film" : "Serie TV"}<span>{requestTab === "movie" ? movieRequests.length : tvRequests.length}</span>
        </button>)}
      </div>
      <div id={`research-request-panel-${tab}`} role="tabpanel" aria-labelledby={`research-request-tab-${tab}`} tabIndex={0}>
        <div className="research-request-group-header">
          <button type="button" className={listExpanded ? undefined : "is-collapsed"} aria-expanded={listExpanded} aria-controls={`research-request-list-${tab}`} onClick={() => setExpandedLists((current) => ({ ...current, [tab]: !current[tab] }))}>
            <span>{tab === "movie" ? "Film" : "Serie TV"}</span>
            <small>{pendingCount}/{tabRequests.length} da gestire</small>
            <ChevronDown size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="research-request-list-actions">
          <WriteAction>
            <Button type="button" variant="ghost" size="compact" disabled={saving || !visibleRequests.length} onClick={() => setAllEnabled(true)}>Seleziona tutti</Button>
            <Button type="button" variant="ghost" size="compact" disabled={saving || !visibleRequests.length} onClick={() => setAllEnabled(false)}>Deseleziona tutti</Button>
            <Button type="button" variant="ghost" size="compact" disabled={saving || !visibleRequests.length} onClick={() => void resetVisibleRules()}><RotateCcw size={14} aria-hidden="true" />Ripristina campi</Button>
          </WriteAction>
          <label className="research-request-availability-toggle"><input type="checkbox" checked={hideAvailable} onChange={(event) => setHideAvailable(event.target.checked)} />Nascondi disponibili{availableCount ? <span>{availableCount}</span> : null}</label>
          <span className="research-request-filter-summary" role="status">{dirty ? "Modifiche in attesa di salvataggio" : visibleCountLabel}</span>
        </div>
        <div id={`research-request-list-${tab}`} className="research-request-list" hidden={!listExpanded}>
          {visibleRequests.length ? visibleRequests.map((request) => <RequestRuleCard key={requestKey(request)} request={request} rule={drafts[requestKey(request)] || defaultRequestRule(request, overview.search_rules)} disabled={saving} onChange={(patch) => updateRule(requestKey(request), patch)} />) : <div className="research-empty-state">Nessuna richiesta visibile con il filtro attuale.</div>}
        </div>
      </div>
    </> : <div className="research-empty-state">Nessuna richiesta Jellyseerr da monitorare.</div>}
    {confirmation.dialog}
  </section>;
}

export { JellyseerrRequestsWorkspace };
