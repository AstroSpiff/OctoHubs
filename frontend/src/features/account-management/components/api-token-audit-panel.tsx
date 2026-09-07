import { Download, RefreshCw, ShieldCheck, ShieldX } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { formatAccountDate, formatApiTokenAction } from "@/features/account-management/account-presentation";
import type { ApiToken, ApiTokenAuditEvent, ApiTokenAuditFilters, ApiTokenAuditResult, ApiTokenAuditVersion } from "@/features/account-management/types";
import {
  isOwnerBoundBrowserActionCancelled,
  useOwnerBoundBrowserAction,
} from "@/features/session/use-owner-bound-browser-action";
import { downloadBrowserFile } from "@/lib/browser-download";

type ApiTokenAuditPanelProps = {
  events: ApiTokenAuditEvent[];
  filters: ApiTokenAuditFilters;
  loading: boolean;
  error?: string;
  tokens: ApiToken[];
  onChangeFilters: (filters: ApiTokenAuditFilters) => void;
  onExport: (filters: ApiTokenAuditFilters, signal?: AbortSignal) => Promise<Blob>;
  onRefresh: () => void;
};

function ApiTokenAuditPanel({ events, error, filters, loading, onChangeFilters, onExport, onRefresh, tokens }: ApiTokenAuditPanelProps) {
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState(false);
  const beginBrowserAction = useOwnerBoundBrowserAction();

  async function exportAudit() {
    const action = beginBrowserAction();
    setExportError("");
    setExporting(true);
    try {
      const audit = await onExport(filters, action.signal);
      downloadBrowserFile(audit, "octohubs-api-token-audit.json", action);
    } catch (requestError) {
      if (isOwnerBoundBrowserActionCancelled(requestError)) return;
      setExportError(requestError instanceof Error ? requestError.message : "Impossibile esportare l'audit token.");
    } finally {
      action.release();
      setExporting(false);
    }
  }

  return (
    <section className="api-token-audit-panel" aria-labelledby="api-token-audit-title">
      <header>
        <div>
          <h3 id="api-token-audit-title" className="contextual-heading" title="Attività API esterna">Audit token</h3>
          <p>Controlla letture, modifiche, operazioni e rifiuti dei client esterni. I segreti non vengono mai registrati.</p>
        </div>
        <div className="api-token-audit-actions">
          <Button type="button" variant="ghost" size="icon" title="Aggiorna audit" aria-label="Aggiorna audit" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={16} aria-hidden="true" />
          </Button>
          <Button type="button" variant="secondary" size="compact" onClick={() => void exportAudit()} disabled={loading || exporting}>
            <Download size={15} aria-hidden="true" />{exporting ? "Esportazione..." : "Esporta JSON"}
          </Button>
        </div>
      </header>
      <div className="api-token-audit-filters">
        <label>
          Token
          <select value={filters.tokenId || ""} onChange={(event) => onChangeFilters({ ...filters, tokenId: event.target.value ? Number(event.target.value) : undefined })}>
            <option value="">Tutti i token</option>
            {tokens.map((token) => <option key={token.id} value={token.id}>{token.name}</option>)}
          </select>
        </label>
        <label>
          Esito
          <select value={filters.result || ""} onChange={(event) => onChangeFilters({ ...filters, result: (event.target.value || undefined) as ApiTokenAuditResult | undefined })}>
            <option value="">Tutti gli esiti</option>
            <option value="allowed">Consentiti</option>
            <option value="denied">Rifiutati</option>
          </select>
        </label>
        <label>
          API
          <select value={filters.apiVersion || ""} onChange={(event) => onChangeFilters({ ...filters, apiVersion: (event.target.value || undefined) as ApiTokenAuditVersion | undefined })}>
            <option value="">Tutte le versioni</option>
            <option value="v1">v1</option>
            <option value="legacy">Legacy</option>
          </select>
        </label>
      </div>
      {error || exportError ? <div className="inline-alert inline-alert--error" role="alert">{exportError || error}</div> : null}
      <div className="api-token-audit-list" aria-live="polite">
        {loading ? <div className="loading-state">Caricamento audit token...</div> : null}
        {!loading && !events.length ? <p className="account-empty">Nessuna attività token per questi filtri.</p> : null}
        {!loading ? events.map((event) => (
          <article key={event.id} className={`api-token-audit-row is-${event.result}`} title={[event.ip_address, event.user_agent].filter(Boolean).join(" · ")}>
            <div className="api-token-audit-result">
              {event.result === "allowed" ? <ShieldCheck size={17} aria-hidden="true" /> : <ShieldX size={17} aria-hidden="true" />}
              <span>{event.result === "allowed" ? "Consentito" : "Rifiutato"}</span>
            </div>
            <div className="api-token-audit-target">
              <strong>{event.token_name}</strong>
              <small><span className={`api-token-audit-version is-${event.api_version}`}>{event.api_version === "v1" ? "v1" : event.api_version === "legacy" ? "Legacy" : "Senza versione"}</span>{formatApiTokenAction(event)}</small>
            </div>
            <time dateTime={event.at || undefined}>{formatAccountDate(event.at)}</time>
          </article>
        )) : null}
      </div>
    </section>
  );
}

export { ApiTokenAuditPanel };
