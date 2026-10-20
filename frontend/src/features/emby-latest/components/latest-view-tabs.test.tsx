import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LatestViewTabs } from "@/features/emby-latest/components/latest-view-tabs";

describe("LatestViewTabs", () => {
  it("exposes the active view and both controlled panels", () => {
    const markup = renderToStaticMarkup(
      <LatestViewTabs activeView="telegram" onChange={() => undefined} />,
    );

    expect(markup).toContain('role="tablist"');
    expect(markup).toContain("Ultime pubblicazioni");
    expect(markup).toContain("Notifiche Telegram");
    expect(markup).toContain(
      'id="latest-view-tab-telegram" type="button" role="tab" aria-selected="true"',
    );
    expect(markup).toContain('aria-controls="latest-view-panel-publications"');
    expect(markup).toContain('aria-controls="latest-view-panel-telegram"');
    expect(markup).toContain("workspace-tabs--section");
  });
});
