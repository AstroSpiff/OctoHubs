import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeRecordList } from "@/features/probe/components/probe-record-list";

describe("ProbeRecordList", () => {
  it("keeps the wide record table reachable by keyboard", () => {
    const markup = renderToStaticMarkup(
      <ProbeRecordList
        kind="history"
        items={[{ item_id: "movie-1", status: "success" }]}
        busy={false}
        onRetry={() => undefined}
      />,
    );

    expect(markup).toContain('role="table"');
    expect(markup).toContain('tabindex="0"');
    expect(markup).toContain("Storico esecuzioni Media Probe");
    expect(markup).toContain('data-label="Titolo"');
    expect(markup).toContain('data-label="Stato"');
  });
});
