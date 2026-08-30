import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeComboCard } from "@/features/probe/components/probe-combo-card";

describe("ProbeComboCard", () => {
  it("mostra ogni contatore del workflow una sola volta nella bacheca operativa", () => {
    const markup = renderToStaticMarkup(
      <ProbeComboCard
        scope="libraries"
        serverStatuses={[]}
        actions={[]}
      />,
    );

    expect(markup.match(/Da fare/g)).toHaveLength(1);
    expect(markup.match(/In esecuzione/g)).toHaveLength(1);
    expect(markup.match(/Completato/g)).toHaveLength(1);
    expect(markup).not.toContain("probe-worker-stats");
  });
});
