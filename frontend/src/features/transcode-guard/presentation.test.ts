import { describe, expect, it } from "vitest";

import { actionSummary, isPlainCorrectStream, isProblemStream, streamPresentation } from "@/features/transcode-guard/presentation";

describe("transcode guard stream presentation", () => {
  it("keeps an exit-only playback correct", () => {
    const stream = { tags: ["corretta"], actions: [{ action: "exit" }], violations_committed: [], ended_at: "2026-08-11T12:00:00Z" };

    expect(isProblemStream(stream)).toBe(false);
    expect(streamPresentation(stream)).toEqual({ label: "Corretto", severity: "ok" });
    expect(isPlainCorrectStream(stream)).toBe(true);
  });

  it("keeps a neutral exit visible without turning it into a problem", () => {
    const stream = { actions: [{ action: "exit" }], violations_committed: [] };

    expect(isProblemStream(stream)).toBe(false);
    expect(streamPresentation(stream)).toEqual({ label: "Uscito", severity: "neutral" });
  });

  it("keeps a warning yellow even when the session later exits", () => {
    const stream = {
      actions: [{ action: "warn" }, { action: "exit", source: "player" }],
      violations_committed: [],
    };

    expect(isProblemStream(stream)).toBe(true);
    expect(streamPresentation(stream)).toEqual({ label: "Avviso", severity: "warning" });
  });

  it("keeps a violation as a problem even after the user exits", () => {
    const stream = { actions: [{ action: "exit" }], violations_committed: ["video_transcode"] };

    expect(isProblemStream(stream)).toBe(true);
  });

  it("treats a guard stop as an intervention", () => {
    const stream = { actions: [{ action: "stop" }], violations_committed: [] };

    expect(isProblemStream(stream)).toBe(true);
    expect(streamPresentation(stream)).toEqual({ label: "Stop del Guard", severity: "error" });
    expect(actionSummary(stream)).toBe("Stop del Guard");
  });

  it("keeps a player pause neutral and distinguishes it from a guard pause", () => {
    const playerPause = { tags: ["corretta"], actions: [{ action: "pause", source: "plugin" }], violations_committed: [] };

    expect(isProblemStream(playerPause)).toBe(false);
    expect(streamPresentation(playerPause)).toEqual({ label: "In pausa", severity: "neutral" });
    expect(actionSummary(playerPause)).toBe("Pausa dal player");
    expect(isProblemStream({ actions: [{ action: "pause", source: "guard" }], violations_committed: [] })).toBe(false);
  });

  it("hides a correct playback even when the user exits normally", () => {
    expect(isPlainCorrectStream({ tags: ["corretta"], violations_committed: [], actions: [] })).toBe(true);
    expect(isPlainCorrectStream({ tags: ["corretta"], violations_committed: [], actions: [{ action: "exit", source: "player" }] })).toBe(true);
    expect(isPlainCorrectStream({ tags: ["corretta"], violations_committed: [], actions: [{ action: "pause", source: "player" }] })).toBe(false);
  });

  it("uses the same readable action vocabulary as stream statistics", () => {
    expect(actionSummary({ actions: [{ action: "warn" }] })).toBe("Avviso inviato");
    expect(actionSummary({ actions: [{ action: "pause", source: "guard" }] })).toBe("Pausa del Guard");
  });
});
