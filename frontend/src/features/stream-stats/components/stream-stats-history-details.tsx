import { formatStatsDuration, formatStatsTime } from "@/features/stream-stats/presentation";
import type { StreamStatsHistory } from "@/features/stream-stats/types";

function StreamStatsHistoryDetails({ stream }: { stream: StreamStatsHistory }) {
  const details: Array<[string, string | undefined]> = [
    ["Dispositivo", stream.device],
    ["Inizio", stream.started_at ? formatStatsTime(stream.started_at) : ""],
    ["Fine", stream.ended_at ? formatStatsTime(stream.ended_at) : "In corso"],
    ["Durata", formatStatsDuration(stream.duration_seconds)],
    ["Avanzamento", typeof stream.playback_percent === "number" ? `${Math.round(stream.playback_percent)}%` : ""],
    ["Regola Guard", stream.rule_name],
    ["Motivo Guard", stream.reason],
  ];
  const items = details.filter((entry): entry is [string, string] => Boolean(entry[1]));

  if (!items.length) return null;
  return (
    <details className="stream-stats-history-details">
      <summary>Dettagli sessione</summary>
      <dl>
        {items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </details>
  );
}

export { StreamStatsHistoryDetails };
