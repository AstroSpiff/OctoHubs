import { describe, expect, it } from "vitest";

import {
  flushLibraryEventKinds,
  librariesUpdatedMessage,
  libraryEventKind,
} from "@/features/libraries/use-libraries-realtime";

describe("libraries realtime events", () => {
  it("separates library lifecycle events from lightweight scan progress", () => {
    expect(libraryEventKind({ MessageType: "RefreshProgress" })).toBe("scan");
    expect(libraryEventKind({ MessageType: "ScheduledTasksInfoStop" })).toBe("library");
    expect(libraryEventKind({ MessageType: "Sessions" })).toBeNull();
  });

  it("refreshes local library configuration and server changes immediately", () => {
    expect(
      libraryEventKind({
        MessageType: librariesUpdatedMessage,
        Data: { scope: "associations" },
      }),
    ).toBe("configuration");
    expect(
      libraryEventKind({
        MessageType: "OctoHubsConfigurationUpdated",
        Data: { scope: "servers" },
      }),
    ).toBe("configuration");
    expect(
      libraryEventKind({
        MessageType: librariesUpdatedMessage,
        Data: { scope: "history" },
      }),
    ).toBe("library");
  });

  it("flushes every distinct domain accumulated in one debounce window", () => {
    const calls: string[] = [];

    flushLibraryEventKinds(new Set(["configuration", "library", "scan"]), {
      onConfigurationChange: () => calls.push("configuration"),
      onLibraryChange: () => calls.push("library"),
      onScanChange: () => calls.push("scan"),
    });

    expect(calls).toEqual(["configuration", "library", "scan"]);
  });
});
