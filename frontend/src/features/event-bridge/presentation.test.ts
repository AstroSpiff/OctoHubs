import { describe, expect, it } from "vitest";

import {
  eventBridgeSaveNotice,
  eventBridgeSettingsEqual,
  eventBridgeSyncSeverity,
  formatEventBridgeTime,
} from "@/features/event-bridge/presentation";
import type { EventBridgeSettings } from "@/features/event-bridge/types";

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
  PLAYBACK_EVENT_NAMES: ["PlaybackStart", "PlaybackStopped"],
  SESSION_EVENT_NAMES: [],
  PLUGIN_EVENT_NAMES: ["plugin.start"],
};

describe("Event Bridge presentation", () => {
  it("formats diagnostics timestamps for the Italian interface", () => {
    expect(formatEventBridgeTime("2026-08-12T10:20:35.249429+00:00")).toMatch(
      /\d{2}:\d{2}:\d{2}/,
    );
    expect(formatEventBridgeTime("")).toBe("Mai");
  });

  it("marks a saved configuration as a warning when plugin delivery fails", () => {
    expect(
      eventBridgeSaveNotice({
        ok: true,
        message: "Event Bridge aggiornato",
        settings_saved: true,
        push: {
          http_pushed: 0,
          websocket_pushed: 0,
          http_failed: ["green: timeout"],
          error: "",
        },
      }),
    ).toMatchObject({ tone: "warning" });
  });

  it("only treats an Event Bridge draft as changed when a setting differs", () => {
    expect(eventBridgeSettingsEqual(settings, { ...settings, PLAYBACK_EVENT_NAMES: [...settings.PLAYBACK_EVENT_NAMES] })).toBe(true);
    expect(eventBridgeSettingsEqual(settings, { ...settings, WEBSOCKET_RECONNECT_SECONDS: 3 })).toBe(false);
    expect(eventBridgeSettingsEqual(settings, { ...settings, PLAYBACK_EVENT_NAMES: [...settings.PLAYBACK_EVENT_NAMES].reverse() })).toBe(false);
  });

  it("treats reported configuration differences as an actionable warning", () => {
    expect(eventBridgeSyncSeverity("aligned")).toBe("ok");
    expect(eventBridgeSyncSeverity("mismatch")).toBe("warning");
    expect(eventBridgeSyncSeverity("unknown")).toBe("unknown");
  });
});
