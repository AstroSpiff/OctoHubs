import { describe, expect, it } from "vitest";

import {
  booleanFields,
  eventFields,
  numericFields,
} from "@/features/event-bridge/settings-catalog";

describe("Event Bridge settings catalog", () => {
  it("uses Italian labels while retaining protocol names", () => {
    expect(booleanFields.find((field) => field.key === "CAPTURE_PLAYBACK_EVENTS")?.label).toBe("Riproduzione");
    expect(booleanFields.find((field) => field.key === "INCLUDE_RAW_PAYLOAD")?.label).toBe("Dati grezzi");
    expect(numericFields.find((field) => field.key === "WEBSOCKET_RECONNECT_SECONDS")?.label).toBe("Riconnessione WS (s)");
    expect(numericFields.find((field) => field.key === "RETRY_COUNT")?.label).toBe("Tentativi HTTP");
    expect(eventFields.find((field) => field.key === "PLAYBACK_EVENT_NAMES")?.label).toBe("Eventi di riproduzione");
  });
});
