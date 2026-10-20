import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  LatestNotificationActions,
  LatestPublicationActions,
  LatestReleaseHeader,
  LatestServerSelector,
} from "@/features/emby-latest/components/latest-release-controls";

describe("LatestReleaseControls", () => {
  it("keeps the page heading separate from the shared server selector", () => {
    const markup = renderToStaticMarkup(
      <LatestReleaseHeader
        workflowing
      />,
    );

    expect(markup).toContain("Pubblicazioni");
    expect(markup).toContain("Un workflow globale e&#x27; in corso");
    expect(markup).not.toContain("Tutti");
    expect(markup).not.toContain("Aggiorna tutto");
    expect(markup).not.toContain("Invia notifiche");
  });

  it("renders one shared server selector for both views", () => {
    const markup = renderToStaticMarkup(
      <LatestServerSelector
        servers={[{ id: "green", name: "Green" }]}
        selectedServer="all"
        onServerChange={() => undefined}
      />,
    );

    expect(markup).toContain('aria-label="Server Emby"');
    expect(markup).toContain("Green");
    expect(markup).toContain("Tutti");
    expect(markup).not.toContain("Aggiorna tutto");
    expect(markup).not.toContain("Invia notifiche");
  });

  it("shows only publication actions in the publications view", () => {
    const markup = renderToStaticMarkup(
      <LatestPublicationActions
        loading={false}
        refreshing={false}
        notifying={false}
        workflowing
        onRefresh={() => undefined}
        onWorkflow={() => undefined}
        onVerify={() => undefined}
      />,
    );

    expect(markup).toContain("Workflow in corso...");
    expect(markup).toContain("Aggiorna");
    expect(markup).toContain("Verifica dati");
    expect(markup).not.toContain("Invia notifiche");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(2);
  });

  it("shows only the send action in the Telegram view", () => {
    const markup = renderToStaticMarkup(
      <LatestNotificationActions
        loading={false}
        refreshing={false}
        notifying={false}
        workflowing={false}
        onNotify={() => undefined}
      />,
    );

    expect(markup).toContain("Invia notifiche");
    expect(markup).not.toContain("Aggiorna tutto");
    expect(markup).not.toContain("Verifica dati");
  });
});
