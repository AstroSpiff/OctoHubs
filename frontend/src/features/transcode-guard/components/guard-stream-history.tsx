import { CheckCircle2, Filter, PauseCircle, Radio, ShieldAlert } from "@/components/ui/icons";
import type { ReactNode } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { WorkspaceCardHeading } from "@/components/ui/workspace-card-heading";
import { actionSummary, formatGuardTime, isPlainCorrectStream, recordList, recordText, streamPresentation } from "@/features/transcode-guard/presentation";
import type { GuardStreamHistory } from "@/features/transcode-guard/types";

function GuardStreamHistory({ history, hideCorrect, onHideCorrectChange, tools }: { history: GuardStreamHistory; hideCorrect: boolean; onHideCorrectChange: (value: boolean) => void; tools?: ReactNode }) {
  const rows = hideCorrect
    ? history.rows.filter((stream) => !isPlainCorrectStream(stream))
    : history.rows;
  return (
    <Card className="guard-history-card">
      <WorkspaceCardHeading
        actions={<div className="guard-history-tools">
          <label title="Nasconde soltanto gli stream corretti senza altri eventi registrati."><Filter size={15} aria-hidden="true" /><input type="checkbox" checked={hideCorrect} onChange={(event) => onHideCorrectChange(event.target.checked)} /> Nascondi corrette</label>
          {tools}
        </div>}
        className="guard-history-heading"
        leading={<Radio size={18} />}
        title="Registro stream"
      />
      <dl className="guard-history-counts">
        <div><dt>Totali</dt><dd>{history.total}</dd></div><div><dt>Corrette</dt><dd>{history.correct}</dd></div>
        <div><dt>Con problemi</dt><dd>{history.violations}</dd></div><div><dt>In corso</dt><dd>{history.active}</dd></div>
      </dl>
      {!rows.length ? <p className="guard-empty-state">{hideCorrect ? "Nessuna riproduzione da mostrare con i filtri correnti." : "Nessuna riproduzione registrata."}</p> : null}
      <div className="guard-stream-list">
        {rows.map((stream, index) => <GuardStreamRow key={recordText(stream, "id", String(index))} stream={stream} />)}
      </div>
    </Card>
  );
}

function GuardStreamRow({ stream }: { stream: Record<string, unknown> }) {
  const status = streamPresentation(stream);
  const identity = [recordText(stream, "server_name", ""), recordText(stream, "user", ""), recordText(stream, "client", "")].filter(Boolean).join(" · ");
  const violations = recordList(stream, "violations_committed");
  const StatusIcon = status.severity === "error" ? ShieldAlert : status.label === "Corretto" ? CheckCircle2 : status.label === "In pausa" ? PauseCircle : Radio;
  return (
    <article className="guard-stream-row">
      <span className={`guard-stream-icon guard-stream-icon--${status.severity}`}><StatusIcon size={18} aria-hidden="true" /></span>
      <div><strong>{recordText(stream, "title", "Riproduzione")}</strong><span>{identity || "Identità stream non disponibile"}</span><small>{actionSummary(stream)}</small></div>
      <div className="guard-stream-meta"><StatusBadge severity={status.severity}>{status.label}</StatusBadge>{violations.length ? <small>{violations.join(", ")}</small> : null}<time>{formatGuardTime(stream.updated_at || stream.ended_at || stream.started_at)}</time></div>
    </article>
  );
}

export { GuardStreamHistory };
