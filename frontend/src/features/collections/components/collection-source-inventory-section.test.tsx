import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { CollectionSourceInventorySection } from "@/features/collections/components/collection-source-inventory-section";

const sourceTypes = [
  { value: "trakt_list", label: "Lista Trakt" },
];

describe("CollectionSourceInventorySection", () => {
  it("shows a loading error without discarding the last available sources", () => {
    const markup = renderToStaticMarkup(
      <CollectionSourceInventorySection
        options={{
          success: true,
          source_types: sourceTypes,
          servers: [],
          trakt_enabled: true,
          mdblist_enabled: true,
        }}
        items={[
          {
            id: "saved-source",
            name: "Preferiti",
            source_type: "trakt_list",
            source_value: "example/preferiti",
          },
        ]}
        hasData
        refreshing={false}
        error="Servizio fonti non raggiungibile."
        busy={false}
        onRefresh={vi.fn()}
        onAdd={vi.fn().mockResolvedValue(undefined)}
        onChoose={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(markup).toContain("Servizio fonti non raggiungibile.");
    expect(markup).toContain("Preferiti");
  });
});
