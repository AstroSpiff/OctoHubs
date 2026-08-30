import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ProbeQueuePanel } from "@/features/probe/components/probe-data-list-panels";

describe("ProbeQueuePanel", () => {
  it("shows an explicit empty state instead of a blank list", () => {
    const markup = renderToStaticMarkup(
      <ProbeQueuePanel
        items={[]}
        serverNames={{}}
        busy={false}
        onClear={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    expect(markup).toContain("La coda è vuota.");
    expect(markup).toContain("Coda di analisi");
    expect(markup).not.toContain("probe-library-groups");
  });

  it("locks per-item removal while another queue operation is active", () => {
    const markup = renderToStaticMarkup(
      <ProbeQueuePanel
        items={[{ item_id: "movie-1", display_name: "Film di prova", server_id: "green" }]}
        serverNames={{ green: "Green" }}
        busy
        onClear={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    expect(markup).toMatch(/<button[^>]*disabled[^>]*>.*Rimuovi<\/button>/);
  });
});
