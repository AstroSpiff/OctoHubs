import { describe, expect, it } from "vitest";

import { formatStatsDuration, outcomePresentation, outcomeTone, streamHistorySignals, trendItemDescription, userSummaryPresentation } from "@/features/stream-stats/presentation";

describe("stream statistics presentation", () => {
  it("keeps a plain exit neutral instead of classifying it as a problem", () => {
    expect(outcomePresentation("exit")).toEqual({ label: "Uscito", severity: "neutral" });
  });

  it("keeps guard stops as enforcement problems", () => {
    expect(outcomePresentation("stop").severity).toBe("error");
  });

  it("keeps neutral exits and corrective changes visually distinct in the user trend", () => {
    expect(outcomeTone("exit")).toBe("neutral");
    expect(outcomeTone("resolution_change")).toBe("warning");
  });

  it("does not show a successful user indicator for exits without a correct outcome", () => {
    expect(userSummaryPresentation({ issue_streams: 0, active: 0, correct: 0, exits: 1, resolution_changes: 0 })).toEqual({ label: "Uscite senza criticità", severity: "neutral" });
    expect(userSummaryPresentation({ issue_streams: 0, active: 0, correct: 1, exits: 1, resolution_changes: 0 })).toEqual({ label: "Riproduzioni corrette", severity: "ok" });
    expect(userSummaryPresentation({ issue_streams: 1, active: 0, correct: 1, exits: 1, resolution_changes: 0 })).toEqual({ label: "Problemi rilevati", severity: "error" });
  });

  it("turns technical codes into readable history signals", () => {
    expect(streamHistorySignals({
      id: "stream-1", at: "", user: "Roy", title: "Film", server_name: "Green", client: "Infuse", device: "Apple TV", quality: "2160p", outcome: "warning", tags: [],
      violations_committed: ["video_transcode"], actions: ["warn", "exit"],
    })).toEqual(["Transcodifica video", "Avviso inviato", "Uscito"]);
    expect(trendItemDescription({ status: "exit", label: "Uscito", at: "2026-08-12T09:15:22+00:00", title: "Film", server: "Green", client: "Infuse", device: "Apple TV", quality: "2160p" })).toContain("Uscito");
  });

  it("keeps player interaction labels neutral in stream history", () => {
    expect(streamHistorySignals({
      id: "stream-2", at: "", user: "Roy", title: "Film", server_name: "Green", client: "Infuse", device: "Apple TV", quality: "2160p", outcome: "correct", tags: [],
      violations_committed: [], actions: ["play", "pause", "unpause", "exit"],
    })).toEqual(["Riproduzione", "Pausa", "Ripresa", "Uscito"]);
  });

  it("uses the Guard action wording for shared history events", () => {
    expect(streamHistorySignals({
      id: "stream-3", at: "", user: "Roy", title: "Film", server_name: "Green", client: "Infuse", device: "Apple TV", quality: "2160p", outcome: "warning", tags: [],
      violations_committed: [], actions: ["warn", "pause"],
    })).toEqual(["Avviso inviato", "Pausa"]);
  });

  it("shares the Guard wording for problem and observed outcomes", () => {
    expect(outcomePresentation("issue")).toEqual({
      label: "Problema rilevato",
      severity: "error",
    });
    expect(outcomePresentation("observed")).toEqual({
      label: "Osservato",
      severity: "neutral",
    });
  });

  it("formats a session duration without making the history row noisy", () => {
    expect(formatStatsDuration(185)).toBe("3 min 5 sec");
    expect(formatStatsDuration(null)).toBe("Non disponibile");
  });
});
