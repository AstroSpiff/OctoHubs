import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceChoiceGroup } from "@/components/ui/workspace-choice-group";

describe("WorkspaceChoiceGroup", () => {
  it("renders one compact, selected control group for pressed choices", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceChoiceGroup
        ariaLabel="Server Emby"
        idPrefix="server"
        value="green"
        options={[
          { id: "green", content: "Green" },
          { id: "red", content: "Red" },
        ]}
        onChange={() => {}}
      />,
    );

    expect(markup).toContain('role="group"');
    expect(markup).toContain('id="server-green"');
    expect(markup).toContain('aria-pressed="true"');
    expect(markup).toContain('class="is-active"');
  });

  it("keeps tab semantics available for local data panels", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceChoiceGroup
        ariaLabel="Dati Probe"
        idPrefix="data"
        mode="tab"
        value="queue"
        options={[
          { id: "queue", content: "Coda", controls: "queue-panel" },
          { id: "history", content: "Storico", controls: "history-panel" },
        ]}
        onChange={() => {}}
      />,
    );

    expect(markup).toContain('role="tablist"');
    expect(markup).toContain('role="tab"');
    expect(markup).toContain('aria-controls="queue-panel"');
    expect(markup).toContain('aria-selected="true"');
  });
});
