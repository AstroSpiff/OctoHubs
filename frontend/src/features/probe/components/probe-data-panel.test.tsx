import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceCapabilityBoundary } from "@/components/app-shell";
import { ProbeDataPanel } from "@/features/probe/components/probe-data-panel";

function renderPanel(dataReady: boolean, dataError: Error | null = null) {
  return renderToStaticMarkup(
    <WorkspaceCapabilityBoundary accessState="editor">
      <ProbeDataPanel
        scope="libraries"
        queue={[]}
        queueLoaded={dataReady}
        history={[]}
        historyLoaded={false}
        errors={[]}
        errorsLoaded={false}
        incomplete={[]}
        incompleteLoaded={false}
        serverNames={{}}
        loading={!dataReady}
        dataReady={dataReady}
        dataError={dataError}
        hasMore={false}
        loadingMore={false}
        busy={false}
        onRefresh={vi.fn()}
        onLoadMore={vi.fn()}
        onActiveTabChange={vi.fn()}
        onClearQueue={vi.fn()}
        onClearHistory={vi.fn()}
        onClearBlacklist={vi.fn()}
        onRemoveQueue={vi.fn()}
        onRemoveBlacklist={vi.fn()}
        onRetryHistory={vi.fn()}
        onRetryBlacklist={vi.fn()}
        onRetryMany={vi.fn()}
      />
    </WorkspaceCapabilityBoundary>,
  );
}

describe("ProbeDataPanel query state", () => {
  it("does not report an empty queue while its snapshot is unresolved", () => {
    const markup = renderPanel(false);

    expect(markup).toContain("Caricamento dati Librerie");
    expect(markup).not.toContain("La coda è vuota");
  });

  it("renders the empty state only for a resolved empty snapshot", () => {
    const markup = renderPanel(true);

    expect(markup).toContain("La coda è vuota");
    expect(markup).not.toContain("Caricamento dati Librerie");
  });
});
