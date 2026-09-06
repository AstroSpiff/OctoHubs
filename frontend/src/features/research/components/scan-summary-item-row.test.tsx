// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScanSummaryItemRow } from "@/features/research/components/scan-summary-item-row";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

describe("ScanSummaryItemRow viewer presentation", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("keeps details readable without rendering selection controls", () => {
    act(() => root.render(
      <WorkspaceCapabilitiesProvider canMutate={false}>
        <ScanSummaryItemRow
          item={{ request_id: 1, title: "Film", results_found: 0 }}
          checked={false}
          qbittorrentAvailable={false}
          disabled={false}
          selectable={false}
          onToggle={vi.fn()}
          onQuickSearch={vi.fn()}
          onCleanup={vi.fn()}
          onAddTerm={vi.fn()}
        />
      </WorkspaceCapabilitiesProvider>,
    ));

    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
    expect(container.querySelector(".scan-summary-toggle")).not.toBeNull();
  });
});
