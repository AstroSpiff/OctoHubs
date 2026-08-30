import { outcomeTone, trendItemDescription } from "@/features/stream-stats/presentation";
import type { StreamStatsTrendItem } from "@/features/stream-stats/types";

function StreamStatsTrend({ trend, onOpenStream }: { trend: StreamStatsTrendItem[]; onOpenStream: (streamId: string) => void }) {
  if (!trend.length) return <span className="stream-stats-trend-empty">Nessun andamento recente</span>;
  return <ol className="stream-stats-trend" aria-label="Andamento delle ultime riproduzioni">
    {trend.slice(0, 12).map((item, index) => {
      const description = trendItemDescription(item);
      return <li key={item.id || `${item.at}-${item.title}-${index}`}><button type="button" className={`stream-stats-trend-dot stream-stats-trend-dot--${outcomeTone(item.status)}`} aria-label={`Apri dettaglio: ${description}`} title={description} onClick={() => item.id && onOpenStream(item.id)} disabled={!item.id} /></li>;
    })}
  </ol>;
}

export { StreamStatsTrend };
