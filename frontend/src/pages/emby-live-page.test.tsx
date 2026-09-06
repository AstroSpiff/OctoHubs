import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceCapabilityBoundary } from "@/components/app-shell";
import { EmbyLivePage } from "@/pages/emby-live-page";


vi.mock("@/features/emby-live/use-emby-live", () => ({
  useEmbyLive: () => ({
    connection: "connected",
    error: null,
    refresh: () => undefined,
    refreshServer: () => Promise.resolve(),
    snapshot: {
      success: true,
      servers: {
        green: {
          server: { id: "green", name: "Green", enabled: true },
          status: { ok: true, version: "4.8.0" },
          running_tasks: [],
          tasks_error: null,
          streams: [],
          streams_error: null,
        },
      },
    },
    updatedAt: 0,
  }),
}));

vi.mock("@/features/emby-live/use-live-server-actions", () => ({
  useLiveServerActions: () => ({
    refreshErrors: {},
    refreshingServerIds: new Set(),
    requestRefresh: () => Promise.resolve(),
    requestRestart: () => Promise.resolve(),
    requestStopTask: () => Promise.resolve(),
    restart: {
      data: null,
      error: null,
      isPending: false,
      variables: undefined,
    },
    stoppingTaskKeys: new Set(),
    taskNotice: null,
    taskStopErrors: {},
  }),
}));

function renderPage(accessState: "viewer" | "editor") {
  return renderToStaticMarkup(
    <WorkspaceCapabilityBoundary accessState={accessState}>
      <EmbyLivePage />
    </WorkspaceCapabilityBoundary>,
  );
}

describe("EmbyLivePage capabilities", () => {
  it("keeps refresh visible but hides every restart action from viewers", () => {
    const markup = renderPage("viewer");

    expect(markup).toContain("Aggiorna");
    expect(markup).not.toContain("Riavvia tutti");
    expect(markup).not.toContain("Riavvia server");
    expect(markup).not.toContain("emby-live-page-restart-action");
  });

  it("shows global and per-server restart actions with mutation access", () => {
    const markup = renderPage("editor");

    expect(markup).toContain("Aggiorna");
    expect(markup).toContain("Riavvia tutti");
    expect(markup).toContain("Riavvia server");
    expect(markup).toContain("emby-live-page-restart-action");
  });
});
