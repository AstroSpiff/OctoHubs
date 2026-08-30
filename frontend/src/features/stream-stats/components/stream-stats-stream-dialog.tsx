import { useQuery } from "@tanstack/react-query";
import { Activity, X } from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { getStreamStatsStreamDetail } from "@/features/stream-stats/api";
import { formatStatsDuration, formatStatsTime, outcomePresentation, streamHistorySignals } from "@/features/stream-stats/presentation";
import type { StreamStatsHistory } from "@/features/stream-stats/types";
import { streamEventLabel } from "@/features/streaming/stream-event-presentation";

function StreamStatsStreamDialog({ streamId, onClose }: { streamId: string | null; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ["stream-stats-detail", streamId],
    queryFn: () => getStreamStatsStreamDetail(streamId || ""),
    enabled: Boolean(streamId),
  });

  if (!streamId) return null;
  const stream = detail.data?.stream;
  const outcome = stream ? outcomePresentation(stream.outcome) : null;

  return (
    <DialogBackdrop className="stream-stats-stream-backdrop" onDismiss={onClose}>
      <section className="stream-stats-stream-dialog" role="dialog" aria-modal="true" aria-labelledby="stream-stats-stream-title">
        <header>
          <div>
            <h2 id="stream-stats-stream-title">Dettaglio riproduzione</h2>
            {stream ? <p>{stream.user} · {stream.server_name} · {stream.client || "Client non disponibile"}</p> : null}
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} title="Chiudi dettaglio riproduzione" aria-label="Chiudi dettaglio riproduzione"><X size={18} aria-hidden="true" /></Button>
        </header>
        {detail.isLoading ? <p className="stream-stats-dialog-state">Caricamento riproduzione monitorata...</p> : null}
        {detail.error ? <p className="stream-stats-dialog-state is-error" role="alert">{detail.error.message}</p> : null}
        {stream && outcome ? <StreamStatsStreamDetail stream={stream} outcome={outcome} /> : null}
        <footer><Button type="button" variant="secondary" onClick={onClose}>Chiudi</Button></footer>
      </section>
    </DialogBackdrop>
  );
}

function StreamStatsStreamDetail({ stream, outcome }: { stream: StreamStatsHistory; outcome: ReturnType<typeof outcomePresentation> }) {
  const signals = streamHistorySignals(stream);
  const details: Array<[string, string]> = [
    ["Titolo", stream.title],
    ["Dispositivo", stream.device || "Non disponibile"],
    ["Qualità", stream.quality || "Non disponibile"],
    ["Inizio", stream.started_at ? formatStatsTime(stream.started_at) : "Non disponibile"],
    ["Fine", stream.ended_at ? formatStatsTime(stream.ended_at) : "In corso"],
    ["Durata", formatStatsDuration(stream.duration_seconds)],
    ["Avanzamento", typeof stream.playback_percent === "number" ? `${Math.round(stream.playback_percent)}%` : "Non disponibile"],
    ["Regola Guard", stream.rule_name || "Nessuna"],
    ["Motivo Guard", stream.reason || "Nessuno"],
  ];
  const events = stream.action_records?.length
    ? stream.action_records
    : stream.actions.map((action) => ({ action, at: undefined }));

  return <div className="stream-stats-stream-dialog-body">
    <div className="stream-stats-stream-status"><span><Activity size={17} aria-hidden="true" /> Esito monitoraggio</span><StatusBadge severity={outcome.severity}>{outcome.label}</StatusBadge></div>
    {signals.length ? <p className={`stream-stats-stream-signals is-${outcome.severity}`}>{signals.join(" · ")}</p> : null}
    <dl className="stream-stats-stream-details">{details.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    <section className="stream-stats-stream-timeline" aria-labelledby="stream-stats-stream-history-title">
      <h3 id="stream-stats-stream-history-title">Storico sessione</h3>
      {events.length ? <ol>{events.map((event, index) => <li key={`${event.at || "event"}-${event.action}-${index}`}><span>{streamEventLabel(event)}</span><time>{event.at ? formatStatsTime(event.at) : "Orario non disponibile"}</time></li>)}</ol> : <p>Nessun evento registrato per questa sessione.</p>}
    </section>
  </div>;
}

export { StreamStatsStreamDialog };
