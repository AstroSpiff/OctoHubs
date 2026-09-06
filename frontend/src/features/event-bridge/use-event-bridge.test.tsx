// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getEventBridgeStatus,
  provisionEventBridgeCredential,
  saveEventBridgeSettings,
} from "@/features/event-bridge/api";
import type {
  EventBridgeCredentialResult,
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
  reject: (reason: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((complete, fail) => {
    resolve = complete;
    reject = fail;
  });
  return { promise, resolve, reject };
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

  it("keeps the saved settings authoritative when the follow-up refetch fails", async () => {
    vi.mocked(getEventBridgeStatus)
      .mockResolvedValueOnce(status)
      .mockRejectedValueOnce(new Error("refresh unavailable"));
    vi.mocked(saveEventBridgeSettings).mockResolvedValue({
      ok: true,
      message: "Event Bridge aggiornato",
      settings_saved: true,
      push: { http_pushed: 1, websocket_pushed: 0, http_failed: [], error: "" },
    });

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <EventBridgeHarness />
        </QueryClientProvider>,
      );
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    const savedDraft = { ...settings, WEBSOCKET_RECONNECT_SECONDS: 3 };
    act(() => latestBridge?.updateDraft(server.id, savedDraft));
    await act(async () => {
      await latestBridge?.save.mutateAsync({ serverId: server.id, settings: savedDraft });
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    expect(latestBridge?.dirtyIds.has(server.id)).toBe(false);
    expect(latestBridge?.drafts[server.id].WEBSOCKET_RECONNECT_SECONDS).toBe(3);
    expect(
      queryClient
        .getQueryData<EventBridgeStatus>(["event-bridge-status"])
        ?.servers[0].settings.WEBSOCKET_RECONNECT_SECONDS,
    ).toBe(3);
  });

  it("removes drafts and dirty state for servers missing after a refetch", async () => {
    vi.mocked(getEventBridgeStatus)
      .mockResolvedValueOnce(status)
      .mockResolvedValueOnce({ ...status, connected: 0, servers: [] });

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <EventBridgeHarness />
        </QueryClientProvider>,
      );
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    act(() => {
      latestBridge?.updateDraft(server.id, {
        ...settings,
        WEBSOCKET_RECONNECT_SECONDS: 2,
      });
    });
    expect(latestBridge?.dirtyIds.has(server.id)).toBe(true);

    await act(async () => {
      await latestBridge?.status.refetch();
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    expect(latestBridge?.dirtyIds.size).toBe(0);
    expect(latestBridge?.drafts[server.id]).toBeUndefined();
  });

  it("keeps concurrent credential provisioning pending and errors keyed by server", async () => {
    const green = deferred<EventBridgeCredentialResult>();
    const blue = deferred<EventBridgeCredentialResult>();
    vi.mocked(getEventBridgeStatus).mockResolvedValue({
      ...status,
      servers: [server, { ...server, id: "blue", name: "Blue" }],
    });
    vi.mocked(provisionEventBridgeCredential).mockImplementation((serverId) =>
      serverId === "green" ? green.promise : blue.promise,
    );

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <EventBridgeHarness />
        </QueryClientProvider>,
      );
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    let greenRequest!: Promise<EventBridgeCredentialResult>;
    let blueRequest!: Promise<EventBridgeCredentialResult>;
    act(() => {
      greenRequest = latestBridge!.provision.mutateAsync("green");
      blueRequest = latestBridge!.provision.mutateAsync("blue");
    });
    expect(latestBridge?.provisionOperations.pendingKeys).toEqual(
      new Set(["green", "blue"]),
    );

    await act(async () => {
      blue.resolve({
        ok: true,
        server_id: "blue",
        configured: true,
        message: "Blue collegato",
      });
      await blueRequest;
    });
    expect(latestBridge?.provisionOperations.pendingKeys).toEqual(
      new Set(["green"]),
    );

    await act(async () => {
      green.reject(new Error("Green non raggiungibile"));
      await expect(greenRequest).rejects.toThrow("Green non raggiungibile");
    });
    expect(latestBridge?.provisionOperations.pendingKeys.size).toBe(0);
    expect(latestBridge?.provisionOperations.errors).toEqual({
      green: "Green non raggiungibile",
    });
  });
});
