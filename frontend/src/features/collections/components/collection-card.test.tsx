import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CollectionCard } from "@/features/collections/components/collection-card";

describe("CollectionCard", () => {
  it("announces an action error on the collection that produced it", () => {
    const markup = renderToStaticMarkup(
      <CollectionCard
        collection={{ id: "watchlist", name: "Watchlist", enabled: true }}
        changing={false}
        syncing={false}
        syncingAll={false}
        actionError="Sincronizzazione Watchlist non riuscita"
        onToggle={() => undefined}
        onSync={() => undefined}
        onEdit={() => undefined}
        onDetails={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(markup).toContain('role="alert"');
    expect(markup).toContain("Sincronizzazione Watchlist non riuscita");
  });

  it("blocks structural actions while the global synchronization is running", () => {
    const markup = renderToStaticMarkup(
      <CollectionCard
        collection={{ id: "watchlist", name: "Watchlist", enabled: true }}
        changing={false}
        syncing
        syncingAll
        onToggle={() => undefined}
        onSync={() => undefined}
        onEdit={() => undefined}
        onDetails={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(markup).toContain("Sincronizzazione globale in corso...");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(4);
  });

  it("renders configured server identities instead of one generic server icon", () => {
    const markup = renderToStaticMarkup(
      <CollectionCard
        collection={{
          id: "trending",
          name: "Trending",
          enabled: true,
          servers: [
            { id: "green", name: "Green", icon: "fa-server", icon_color: "#19a36f" },
            { id: "purple", name: "Purple", icon: "fa-film", icon_color: "#8B5CF6", icon_style: "regular" },
          ],
          last_sync_message: "Green 35/45 · Purple 90/100",
          last_sync_per_server: [
            { server_id: "green", server_label: "Green", synced_at: "2026-08-21T20:10:00+00:00", matched: 35, candidates: 45, missing: 10 },
            { server_id: "purple", server_label: "Purple", synced_at: "2026-08-21T20:12:00+00:00", matched: 90, candidates: 100, missing: 0 },
          ],
        }}
        changing={false}
        syncing={false}
        syncingAll={false}
        onToggle={() => undefined}
        onSync={() => undefined}
        onEdit={() => undefined}
        onDetails={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(markup).toContain("Green");
    expect(markup).toContain("Purple");
    expect(markup).toContain("#19a36f");
    expect(markup).toContain("#8B5CF6");
    expect(markup).toContain('dateTime="2026-08-21T20:10:00+00:00"');
    expect(markup).toContain('dateTime="2026-08-21T20:12:00+00:00"');
    expect(markup).toContain("35/45");
    expect(markup).toContain("10 manc.");
    expect(markup).toContain("90/100");
    expect(markup).not.toContain("Green 35/45 · Purple 90/100");
  });
});
