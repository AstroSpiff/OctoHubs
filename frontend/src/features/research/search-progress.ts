import type { StreamingSearchProgress } from "@/features/research/types";

function searchProgressMessage(progress: StreamingSearchProgress): string {
  const completed = Math.max(0, progress.completedQueries || 0);
  const total = Math.max(0, progress.totalQueries || 0);
  const source = [progress.latestQuery, progress.latestIndexer]
    .filter((value): value is string => Boolean(value))
    .join(" · ");

  if (total) {
    const summary = `Query completate ${Math.min(completed, total)} di ${total}`;
    return source ? `${summary} · ${source}` : summary;
  }

  return source ? `Ricerca in corso · ${source}` : "In attesa di risposte dagli indexer.";
}

export { searchProgressMessage };
