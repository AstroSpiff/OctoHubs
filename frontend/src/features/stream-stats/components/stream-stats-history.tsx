import { History } from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { WorkspaceCardHeading } from "@/components/ui/workspace-card-heading";
import { StreamStatsHistoryDetails } from "@/features/stream-stats/components/stream-stats-history-details";
import { formatStatsTime, outcomePresentation, streamHistorySignals } from "@/features/stream-stats/presentation";
import type { StreamStatsHistory } from "@/features/stream-stats/types";

function StreamStatsHistory({ history }: { history: StreamStatsHistory[] }) {
  return (
    <Card className="stream-stats-history-card">
      <WorkspaceCardHeading
        count={history.length}
        leading={<History size={18} />}
        title="Ultime riproduzioni"
      />
      {!history.length ? <p className="stream-stats-empty">Nessuna riproduzione con i filtri selezionati.</p> : null}
      <div className="stream-stats-history-list">{history.map((stream) => <StreamStatsHistoryRow key={stream.id} stream={stream} />)}</div>
    </Card>
  );
}

function StreamStatsHistoryRow({ stream }: { stream: StreamStatsHistory }) {
  const outcome = outcomePresentation(stream.outcome);
  const details = [stream.server_name, stream.client, stream.quality].filter(Boolean).join(" · ");
  const signals = streamHistorySignals(stream);
  return <article className="stream-stats-history-row"><div><strong>{stream.user} <span>{stream.title}</span></strong><small>{details || "Dettagli stream non disponibili"}</small>{signals.length ? <em className={`stream-stats-history-signals stream-stats-history-signals--${outcome.severity}`}>{signals.join(" · ")}</em> : null}<StreamStatsHistoryDetails stream={stream} /></div><div><StatusBadge severity={outcome.severity}>{outcome.label}</StatusBadge><time>{formatStatsTime(stream.at)}</time></div></article>;
}

export { StreamStatsHistory };
