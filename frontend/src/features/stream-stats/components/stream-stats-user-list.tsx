import { AlertTriangle, CheckCircle2, CircleDashed, Timer, Users } from "@/components/ui/icons";

import { Card } from "@/components/ui/card";
import { WorkspaceCardHeading } from "@/components/ui/workspace-card-heading";
import { StreamStatsTrend } from "@/features/stream-stats/components/stream-stats-trend";
import { formatStatsTime, userSummaryPresentation } from "@/features/stream-stats/presentation";
import type { StreamStatsUser } from "@/features/stream-stats/types";

function StreamStatsUserList({ users, onOpenStream }: { users: StreamStatsUser[]; onOpenStream: (streamId: string) => void }) {
  return (
    <Card className="stream-stats-users-card">
      <WorkspaceCardHeading
        count={users.length}
        leading={<Users size={18} />}
        title="Utenti osservati"
      />
      {!users.length ? <p className="stream-stats-empty">Nessun dato utente con i filtri selezionati.</p> : null}
      <div className="stream-stats-user-list">{users.map((user) => <StreamStatsUserRow key={user.user} user={user} onOpenStream={onOpenStream} />)}</div>
    </Card>
  );
}

function StreamStatsUserRow({ user, onOpenStream }: { user: StreamStatsUser; onOpenStream: (streamId: string) => void }) {
  const presentation = userSummaryPresentation(user);
  const Icon = presentation.severity === "error" || presentation.severity === "warning" ? AlertTriangle : presentation.severity === "ok" ? CheckCircle2 : presentation.severity === "info" ? Timer : CircleDashed;
  const details = [user.servers.map((item) => item.name).join(", "), user.clients.map((item) => item.name).join(", ")].filter(Boolean).join(" · ");
  return (
    <article className="stream-stats-user-row">
      <span className={`stream-stats-user-icon is-${presentation.severity}`} title={presentation.label} aria-label={presentation.label} role="img"><Icon size={18} aria-hidden="true" /></span>
      <div className="stream-stats-user-identity"><strong>{user.user}</strong><span>{details || "Nessun dettaglio client disponibile"}</span><small>Ultimo stream: {formatStatsTime(user.last_seen_at)}</small></div>
      <dl className="stream-stats-user-metrics"><div><dt>Stream</dt><dd>{user.streams}</dd></div><div><dt>Problemi</dt><dd>{user.issue_streams}<small>{user.problem_rate}%</small></dd></div></dl>
      <div className="stream-stats-user-outcomes" aria-label={`Esiti di ${user.user}`}><span title="Risolti"><b>{user.resolved}</b> risolti</span><span title="Stop eseguiti dal Guard"><b>{user.stops}</b> stop</span><span title="Uscite utente"><b>{user.exits}</b> uscite</span><span title="Ricadute"><b>{user.relapses}</b> ricadute</span></div>
      <StreamStatsTrend trend={user.trend || []} onOpenStream={onOpenStream} />
    </article>
  );
}

export { StreamStatsUserList };
