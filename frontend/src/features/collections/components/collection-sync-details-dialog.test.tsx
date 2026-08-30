import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CollectionSyncDetailsDialog } from "@/features/collections/components/collection-sync-details-dialog";

describe("CollectionSyncDetailsDialog", () => {
  it("keeps a direct close action in the results header", () => {
    const markup = renderToStaticMarkup(
      <CollectionSyncDetailsDialog
        collection={{ id: "watchlist", name: "Watchlist", enabled: true }}
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain('aria-label="Chiudi dettagli sincronizzazione"');
    expect(markup).toContain("Chiudi");
  });
});
