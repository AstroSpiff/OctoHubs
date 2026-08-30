import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LatestReleaseControls } from "@/features/emby-latest/components/latest-release-controls";

describe("LatestReleaseControls", () => {
  it("holds conflicting actions while the global workflow is active", () => {
    const markup = renderToStaticMarkup(
      <LatestReleaseControls
        servers={[]}
        selectedServer="all"
        displayLimit={10}
        loading={false}
        refreshing={false}
        notifying={false}
        workflowing
        onServerChange={() => undefined}
        onLimitChange={() => undefined}
        onRefresh={() => undefined}
        onNotify={() => undefined}
        onWorkflow={() => undefined}
        onVerify={() => undefined}
      />,
    );

    expect(markup).toContain("Workflow in corso...");
    expect(markup).toContain("Un workflow globale e&#x27; in corso");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(3);
  });
});
