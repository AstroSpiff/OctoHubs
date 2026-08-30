import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SearchResultBucket } from "@/features/research/components/search-result-bucket";

describe("SearchResultBucket", () => {
  it("labels the horizontally scrollable results table", () => {
    const markup = renderToStaticMarkup(
      <SearchResultBucket
        bucket={{ key: "1080p", label: "1080p Full HD", items: [] }}
        canSend={false}
        selected={new Set()}
        onNotice={() => undefined}
        onToggle={() => undefined}
        onToggleItems={() => undefined}
      />,
    );

    expect(markup).toContain('role="region"');
    expect(markup).toContain('tabindex="0"');
    expect(markup).toContain("Scorri orizzontalmente per vedere tutte le colonne.");
  });
});
