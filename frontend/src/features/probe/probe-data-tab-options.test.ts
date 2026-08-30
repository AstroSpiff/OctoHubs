import { describe, expect, it } from "vitest";

import { probeDataTabOptions } from "@/features/probe/probe-data-tab-options";

describe("probeDataTabOptions", () => {
  it("keeps the four operational data areas with their live counts", () => {
    expect(
      probeDataTabOptions({
        queueCount: 2,
        historyCount: 7,
        errorCount: 1,
        incompleteCount: 3,
        showSettings: false,
      }),
    ).toEqual([
      { id: "queue", label: "Coda", count: 2 },
      { id: "history", label: "Storico", count: 7 },
      { id: "errors", label: "Errori", count: 1 },
      { id: "incomplete", label: "Incompleti", count: 3 },
    ]);
  });

  it("exposes configuration only when the current scope provides it", () => {
    expect(
      probeDataTabOptions({
        queueCount: 0,
        historyCount: 0,
        errorCount: 0,
        incompleteCount: 0,
        showSettings: true,
      }).at(-1),
    ).toEqual({ id: "settings", label: "Configurazione" });
  });
});
