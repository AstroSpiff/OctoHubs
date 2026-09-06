import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventBridgeWorkspace } from "@/features/event-bridge/components/event-bridge-workspace";

const bridgeState = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));

vi.mock("@/features/event-bridge/use-event-bridge", () => ({
  useEventBridge: () => bridgeState.current,
}));
vi.mock("@/lib/use-unsaved-changes-navigation-guard", () => ({
  useUnsavedChangesNavigationGuard: vi.fn(),
}));

describe("EventBridgeWorkspace query state", () => {
  beforeEach(() => {
    bridgeState.current = {
      dirtyIds: new Set(),
      drafts: {},
      notice: null,
      provisionOperations: { errors: {}, pendingKeys: new Set() },
      save: { error: null, isError: false, isPending: false, variables: undefined },
      servers: [],
      status: {
        data: undefined,
        error: null,
        isFetching: true,
        refetch: vi.fn(),
      },
      updateDraft: vi.fn(),
    };
  });

  it("does not publish zero metrics while status is unresolved", () => {
    const markup = renderToStaticMarkup(<EventBridgeWorkspace />);

    expect(markup).toContain("Caricamento Event Bridge");
    expect(markup).not.toContain("Server configurati");
    expect(markup).not.toContain("Collegamenti Event Bridge");
  });

  it("publishes zero metrics only after a successful empty snapshot", () => {
    bridgeState.current = {
      ...bridgeState.current,
      status: {
        data: { connected: 0, credential_configured: 0, servers: [] },
        error: null,
        isFetching: false,
        refetch: vi.fn(),
      },
    };

    const markup = renderToStaticMarkup(<EventBridgeWorkspace />);

    expect(markup).toContain("Server configurati");
    expect(markup).toContain("Collegamenti Event Bridge");
    expect(markup).not.toContain("Caricamento Event Bridge");
  });
});
