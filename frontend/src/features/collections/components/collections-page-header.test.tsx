import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { CollectionsPageHeader } from "@/features/collections/components/collections-page-header";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

function renderHeader(canMutate: boolean) {
  return renderToStaticMarkup(
    <WorkspaceCapabilitiesProvider canMutate={canMutate}>
      <CollectionsPageHeader
        optionsLoading={false}
        refreshing={false}
        syncing={false}
        onOpenSources={vi.fn()}
        onRefresh={vi.fn()}
        onCreate={vi.fn()}
        onSyncAll={vi.fn()}
      />
    </WorkspaceCapabilitiesProvider>,
  );
}

describe("CollectionsPageHeader capabilities", () => {
  it("hides source refresh and other mutations from viewers", () => {
    const markup = renderHeader(false);

    expect(markup).toContain("Aggiorna");
    expect(markup).not.toContain("Fonti");
    expect(markup).not.toContain("Nuova collezione");
    expect(markup).not.toContain("Sincronizza attive");
  });

  it("keeps collection mutations available to editors and admins", () => {
    const markup = renderHeader(true);

    expect(markup).toContain("Fonti");
    expect(markup).toContain("Nuova collezione");
    expect(markup).toContain("Sincronizza attive");
  });
});
