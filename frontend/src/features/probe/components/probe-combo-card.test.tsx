import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeComboCard } from "@/features/probe/components/probe-combo-card";

describe("ProbeComboCard", () => {
  it("mostra ogni contatore del workflow una sola volta nella bacheca operativa", () => {
    const markup = renderToStaticMarkup(
      <ProbeComboCard
        scope="libraries"
        serverStatuses={[]}
        actions={[]}
      />,
    );

    expect(markup.match(/Da fare/g)).toHaveLength(1);
    expect(markup.match(/In esecuzione/g)).toHaveLength(1);
    expect(markup.match(/Completato/g)).toHaveLength(1);
    expect(markup).not.toContain("probe-worker-stats");
  });

  it("mostra nome e progresso propri per ogni libreria", () => {
    const markup = renderToStaticMarkup(
      <ProbeComboCard
        scope="libraries"
        serverStatuses={[{
          serverId: "black",
          serverName: "BlackPrimrose",
          libraryNames: { films: "Film", series: "Serie TV" },
          processingStatus: {
            running: true,
            started_at: "2026-09-19T08:01:00Z",
            current_library_id: "films",
            current_item: "Film corrente",
            target_library_ids: ["films", "series"],
            library_queue_totals: { films: 200, series: 400 },
            library_queue_results: {
              films: { processed: 10 },
              series: { processed: 0 },
            },
          },
        }]}
        actions={[]}
      />,
    );

    expect(markup).toContain("BlackPrimrose · Film");
    expect(markup).toContain("BlackPrimrose · Serie TV");
    expect(markup).toContain("10/200 · 5%");
    expect(markup).toContain("0/400 · 0%");
    expect(markup.match(/Film corrente/g)).toHaveLength(1);
  });
});
