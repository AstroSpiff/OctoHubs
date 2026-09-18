import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ProbeQueuePanel } from "@/features/probe/components/probe-data-list-panels";

describe("ProbeQueuePanel", () => {
  it("shows an explicit empty state instead of a blank list", () => {
    const markup = renderToStaticMarkup(
      <ProbeQueuePanel
        groups={[]}
        scope="libraries"
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

  it("renders title counts without materializing file rows", () => {
    const markup = renderToStaticMarkup(
      <ProbeQueuePanel
        groups={[{
          server_id: "green",
          library_id: "movies",
          library_name: "Film",
          group_type: "movie",
          group_id: "movie-1",
          title: "Film di prova",
          file_count: 275,
        }]}
        scope="libraries"
        serverNames={{ green: "Green" }}
        busy
        onClear={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    expect(markup).toContain("Film di prova");
    expect(markup).toContain("275 file");
    expect(markup).not.toContain("Rimuovi");
  });
});
