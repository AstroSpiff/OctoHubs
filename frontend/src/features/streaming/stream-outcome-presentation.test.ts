import { describe, expect, it } from "vitest";

import { streamOutcomePresentation } from "@/features/streaming/stream-outcome-presentation";

describe("stream outcome presentation", () => {
  it("keeps neutral exits separate from actual Guard interventions", () => {
    expect(streamOutcomePresentation("exit")).toEqual({
      label: "Uscito",
      severity: "neutral",
    });
    expect(streamOutcomePresentation("stop")).toEqual({
      label: "Stop del Guard",
      severity: "error",
    });
  });

  it("uses the same readable treatment for corrections and problems", () => {
    expect(streamOutcomePresentation("resolution_change")).toEqual({
      label: "Cambio risoluzione",
      severity: "warning",
    });
    expect(streamOutcomePresentation("issue")).toEqual({
      label: "Problema rilevato",
      severity: "error",
    });
  });
});
