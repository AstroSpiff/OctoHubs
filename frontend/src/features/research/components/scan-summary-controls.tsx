import { CircleStop, Play, RefreshCw } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { formatResearchDate } from "@/features/research/presentation";
import type { ResearchOverview, ResearchNotice } from "@/features/research/types";

function ScanSummaryControls({
  scan,
  hasConfig,
  busy,
  notice,
  generatedAt,
  onStart,
  onStop,
  onRefresh,
}: {
  scan: ResearchOverview["scan"];
  hasConfig: boolean;
  busy: boolean;
  notice: ResearchNotice | null;
  generatedAt: string | null | undefined;
  onStart: () => void;
  onStop: () => void;
  onRefresh: () => void;
}) {
  const total = numberValue(scan.total);
  const completed = numberValue(scan.completed);
  const percentage = total ? Math.min(100, Math.round((completed / total) * 100)) : 0;

  return <section className="research-card" aria-labelledby="scan-control-title">
    <header className="research-card-heading">
      <div>
        <h3 id="scan-control-title" className="contextual-heading" title="Controllo ricerche">Ricerca automatica</h3>
        <p>{stringValue(scan.message) || "In attesa"}{scan.current_title ? ` · ${String(scan.current_title)}` : ""}</p>
      </div>
      <div className="research-scan-actions">
        {scan.running ? <Button type="button" requiresWriteAccess variant="danger" size="compact" disabled={busy} onClick={onStop}><CircleStop size={15} aria-hidden="true" /> Ferma</Button> : <Button type="button" requiresWriteAccess variant="primary" size="compact" disabled={!hasConfig || busy} onClick={onStart}><Play size={15} aria-hidden="true" /> Avvia ricerca completa</Button>}
        <Button type="button" variant="ghost" size="icon" title="Aggiorna stato ricerca" aria-label="Aggiorna stato ricerca" disabled={busy} onClick={onRefresh}><RefreshCw size={16} aria-hidden="true" /></Button>
      </div>
    </header>
    <div className="research-scan-status">
      <div><span>Avanzamento</span><strong>{total ? `${completed} / ${total}` : "In attesa"}</strong></div>
      <div className="research-progress"><span style={{ width: `${percentage}%` }} /></div>
      {generatedAt ? <small>Ultimo riepilogo: {formatResearchDate(generatedAt)}</small> : null}
    </div>
    {notice ? <div className={`inline-alert inline-alert--${notice.tone}`} role={notice.tone === "error" ? "alert" : "status"}>{notice.message}</div> : null}
  </section>;
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

export { ScanSummaryControls };
