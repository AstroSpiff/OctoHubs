import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CollectionsList } from "@/features/collections/components/collections-list";

describe("CollectionsList", () => {
  it("shows the create card before existing collections", () => {
    const markup = renderToStaticMarkup(
      <CollectionsList
        collections={[{ id: "watchlist", name: "Watchlist", enabled: true }]}
        syncingAll={false}
        isSyncingCollection={() => false}
        onToggle={() => undefined}
        onSync={() => undefined}
        onEdit={() => undefined}
        onDetails={() => undefined}
        onDelete={() => undefined}
        onCreate={() => undefined}
      />,
    );

    expect(markup.indexOf("Nuova collezione")).toBeLessThan(
      markup.indexOf("Watchlist"),
    );
  });
});
