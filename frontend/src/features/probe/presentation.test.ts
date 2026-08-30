import { describe, expect, it } from "vitest";

import {
  mergeProbeWorkerStatuses,
  probeProgress,
  probeStatusLabel,
} from "@/features/probe/presentation";

describe("probeStatusLabel", () => {
  it("distingue uno stato pronto da un worker in esecuzione", () => {
    expect(probeStatusLabel()).toBe("Pronto");
    expect(probeStatusLabel({ running: true })).toBe("In esecuzione");
  });
});

describe("mergeProbeWorkerStatuses", () => {
  it("combina contatori e code senza duplicare un totale condiviso", () => {
    const status = mergeProbeWorkerStatuses([
      { running: false, found: 3, processed: 2, total: 4, queue: [{ id: "first", type: "discovery" }] },
      { running: true, phase: "processing", found: 2, processed: 1, incomplete: 1, total: 5, queue: [{ id: "second", type: "processing" }] },
    ]);

    expect(status).toMatchObject({ running: true, phase: "processing", found: 5, processed: 3, incomplete: 1, total: 5 });
    expect(status?.queue).toHaveLength(2);
  });

  it("mostra un log solo da un worker attivo", () => {
    const status = mergeProbeWorkerStatuses([
      { running: false, last_log: "Operazione terminata" },
      { running: true },
    ]);

    expect(status?.last_log).toBe("1 server in esecuzione");
  });
});

describe("probeProgress", () => {
  it("calcola l'avanzamento e non supera il totale", () => {
    expect(probeProgress({ processed: 4, incomplete: 2, errors: 1, total: 5 })).toEqual({ completed: 5, total: 5 });
  });

  it("non mostra una barra senza un totale disponibile", () => {
    expect(probeProgress({ processed: 4 })).toBeUndefined();
  });
});
