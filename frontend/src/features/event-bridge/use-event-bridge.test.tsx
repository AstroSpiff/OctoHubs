// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getEventBridgeStatus,
  saveEventBridgeSettings,
} from "@/features/event-bridge/api";
import type {
  EventBridgeSaveResult,
  EventBridgeServer,
  EventBridgeSettings,
  EventBridgeStatus,
} from "@/features/event-bridge/types";
import { useEventBridge } from "@/features/event-bridge/use-event-bridge";

vi.mock("@/features/event-bridge/api", () => ({
  getEventBridgeStatus: vi.fn(),
  saveEventBridgeSettings: vi.fn(),
  provisionEventBridgeCredential: vi.fn(),
}));

vi.mock("@/features/event-bridge/use-event-bridge-realtime", () => ({
  useEventBridgeRealtime: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

const settings: EventBridgeSettings = {
  ENABLED: true,
  WEBSOCKET_ENABLED: true,
  HTTP_FALLBACK_ENABLED: true,
  WEBSOCKET_RECONNECT_SECONDS: 5,
  CAPTURE_PLAYBACK_EVENTS: true,
  CAPTURE_SESSION_EVENTS: true,
  CAPTURE_PLUGIN_EVENTS: true,
  EVENT_BATCH_INTERVAL_SECONDS: 1,
  HTTP_TIMEOUT_SECONDS: 5,
  RETRY_COUNT: 1,
  INCLUDE_RAW_PAYLOAD: false,
  PLAYBACK_EVENT_NAMES: ["PlaybackStart"],
  SESSION_EVENT_NAMES: [],
  PLUGIN_EVENT_NAMES: ["plugin.start"],
};

const server: EventBridgeServer = {
  id: "green",
  name: "Green",
  settings_editable: true,
  credential: { configured: true, label: "Credenziale per-server", class_name: "status-ok" },
  settings,
  transport: { label: "WebSocket connesso", class_name: "status-ok" },
  config_ack: { label: "", class_name: "", title: "" },
  diagnostics: {
    sync_status: "aligned",
    sync_label: "Configurazione allineata",
    sync_class: "status-ok",
    plugin_version: "0.4.2",
    plugin_version_label: "Plugin 0.4.2",
    last_seen_at: "",
    last_event: "",
    last_event_at: "",
    last_config_sent_at: "",
    last_config_ack_at: "",
    last_config_transport_label: "Non rilevato",
    last_config_ack_error: "",
    last_plugin_settings_at: "",
    target_count_label: "1",
    plugin_targets: [],
    diffs: [],
  },
};

const status: EventBridgeStatus = {
  ok: true,
  connected: 1,
  webhook_secret_configured: true,
  credential_configured: 1,
  servers: [server],
};

let latestBridge: ReturnType<typeof useEventBridge> | undefined;

function EventBridgeHarness() {
  latestBridge = useEventBridge();
  return null;
}

describe("useEventBridge", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latestBridge = undefined;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    queryClient.clear();
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("keeps a newer draft dirty after an older save finishes", async () => {
    const saveResult = deferred<EventBridgeSaveResult>();
    vi.mocked(getEventBridgeStatus).mockResolvedValue(status);
    vi.mocked(saveEventBridgeSettings).mockReturnValue(saveResult.promise);

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <EventBridgeHarness />
        </QueryClientProvider>,
      );
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    const savedDraft = { ...settings, WEBSOCKET_RECONNECT_SECONDS: 3 };
    const newerDraft = { ...settings, WEBSOCKET_RECONNECT_SECONDS: 2 };
    act(() => {
      latestBridge?.updateDraft(server.id, savedDraft);
      latestBridge?.save.mutate({ serverId: server.id, settings: savedDraft });
      latestBridge?.updateDraft(server.id, newerDraft);
    });

    await act(async () => {
      saveResult.resolve({
        ok: true,
        message: "Event Bridge aggiornato",
        settings_saved: true,
        push: { http_pushed: 1, websocket_pushed: 0, http_failed: [], error: "" },
      });
      await saveResult.promise;
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    expect(latestBridge?.dirtyIds.has(server.id)).toBe(true);
    expect(latestBridge?.drafts[server.id].WEBSOCKET_RECONNECT_SECONDS).toBe(2);
  });
});
