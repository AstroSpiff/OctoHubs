import { ChevronRight, Trash2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { probeItemLabel } from "@/features/probe/presentation";
import type { ProbeListItem } from "@/features/probe/probe-grouping";
import type { ProbeQueueItem } from "@/features/probe/types";

function ProbeQueueGroups({
  items,
  busy,
  onRemove,
}: {
  items: ProbeListItem[];
  busy: boolean;
  onRemove: (item: ProbeQueueItem) => void;
}) {
  const queueItems = items as ProbeQueueItem[];
  const series = new Map<string, ProbeQueueItem[]>();
  const movies: ProbeQueueItem[] = [];

  queueItems.forEach((item) => {
    if (!item.series_name) {
      movies.push(item);
      return;
    }
    const episodes = series.get(item.series_name) || [];
    episodes.push(item);
    series.set(item.series_name, episodes);
  });

  return (
    <div className="probe-queue-groups">
      {[...series.entries()]
        .sort(([left], [right]) => left.localeCompare(right, "it"))
        .map(([seriesName, episodes]) => (
          <details key={seriesName} className="probe-series-group">
            <summary>
              <span>
                <ChevronRight size={15} aria-hidden="true" />
                {seriesLabel(seriesName, episodes)}
              </span>
              <strong>{episodes.length} episodi</strong>
            </summary>
            <div>
              {episodes.sort(compareEpisodes).map((item, index) => (
                <ProbeQueueRow
                  key={`${item.item_id}:${item.media_source_id || index}`}
                  item={item}
                  busy={busy}
                  onRemove={onRemove}
                />
              ))}
            </div>
          </details>
        ))}
      {movies
        .sort((left, right) =>
          probeItemLabel(left).localeCompare(probeItemLabel(right), "it"),
        )
        .map((item, index) => (
          <ProbeQueueRow
            key={`${item.item_id}:${item.media_source_id || index}`}
            item={item}
            busy={busy}
            onRemove={onRemove}
          />
        ))}
    </div>
  );
}

function ProbeQueueRow({
  item,
  busy,
  onRemove,
}: {
  item: ProbeQueueItem;
  busy: boolean;
  onRemove: (item: ProbeQueueItem) => void;
}) {
  return (
    <article className="probe-queue-row">
      <div>
        <strong>{probeItemLabel(item)}</strong>
        <span>{item.path || "Percorso non disponibile"}</span>
      </div>
      <Button
        type="button"
        requiresWriteAccess
        variant="ghost"
        size="compact"
        title="Rimuovi dalla coda"
        onClick={() => onRemove(item)}
        disabled={busy}
      >
        <Trash2 size={14} aria-hidden="true" />
        Rimuovi
      </Button>
    </article>
  );
}

function compareEpisodes(left: ProbeQueueItem, right: ProbeQueueItem) {
  return (
    Number(left.season_number || 0) - Number(right.season_number || 0) ||
    Number(left.episode_number || 0) - Number(right.episode_number || 0)
  );
}

function seriesLabel(seriesName: string, episodes: ProbeQueueItem[]) {
  const year = episodes.find((item) => item.year)?.year;
  return year && !/\(\d{4}\)/.test(seriesName)
    ? `${seriesName} (${year})`
    : seriesName;
}

export { ProbeQueueGroups };
