import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { EventBridgeServerCard } from "@/features/event-bridge/components/event-bridge-server-card";
import type { EventBridgeServer, EventBridgeSettings } from "@/features/event-bridge/types";

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
  icon: "fa-film",
  icon_color: "#8B5CF6",
  icon_style: "regular",
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
    last_config_transport_label: "HTTP",
    last_config_ack_error: "",
    last_plugin_settings_at: "",
    target_count_label: "1",
    plugin_targets: [],
    diffs: [],
  },
};

describe("EventBridgeServerCard", () => {
  it("keeps the configured server identity distinct from the transport status", () => {
    const markup = renderToStaticMarkup(
      <EventBridgeServerCard
        server={server}
        draft={settings}
        dirty={false}
        saving={false}
        provisioning={false}
        locked={false}
        saveError=""
        provisionError=""
        onChange={() => undefined}
        onSave={() => undefined}
        onProvision={() => undefined}
      />,
    );

    expect(markup).toContain("Green");
    expect(markup).toContain("data-prefix=\"fas\"");
    expect(markup).toContain("color:#8B5CF6");
    expect(markup).toContain("WebSocket connesso");
    expect(markup).toContain("Canale config");
    expect(markup).toContain("HTTP");
    expect(markup).toContain("Credenziale per-server");
  });
});
