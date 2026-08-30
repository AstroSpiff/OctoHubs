import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeWorkspace } from "@/features/probe/components/probe-workspace";

describe("ProbeWorkspace", () => {
  it("uses a labelled section because scope navigation changes the route", () => {
    const markup = renderToStaticMarkup(
      <ProbeWorkspace
        scope="recent"
        servers={[]}
        serverId="all"
        onServerChange={() => undefined}
      >
        Contenuto Probe
      </ProbeWorkspace>,
    );

    expect(markup).toContain('id="probe-recent-workspace"');
    expect(markup).toContain('aria-labelledby="probe-workspace-title"');
    expect(markup).not.toContain('role="tabpanel"');
  });
});
