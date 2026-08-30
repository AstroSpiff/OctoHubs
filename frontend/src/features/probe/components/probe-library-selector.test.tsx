import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ProbeLibrarySelector } from "@/features/probe/components/probe-library-selector";

describe("ProbeLibrarySelector", () => {
  it("separa le librerie nelle tre categorie operative", () => {
    const markup = renderToStaticMarkup(
      <ProbeLibrarySelector
        libraries={[
          { id: "movie", name: "Cinema", collection_type: "movies" },
          { id: "series", name: "Serie", collection_type: "tvshows" },
          { id: "other", name: "Documentari", collection_type: "boxsets" },
        ]}
        selected={[]}
        disabled={false}
        onChange={vi.fn()}
      />,
    );

    expect(markup).toContain("Film");
    expect(markup).toContain("Serie TV");
    expect(markup).toContain("Cartelle e altro");
    expect(markup).toContain("probe-library-selector-group");
  });
});
