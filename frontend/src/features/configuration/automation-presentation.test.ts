import { describe, expect, it } from "vitest";

import { formatConfigurationMoment, requestRefreshPresentation } from "@/features/configuration/automation-presentation";

describe("request refresh presentation", () => {
  it("reports skipped refreshes with their operational detail and a readable timestamp", () => {
    expect(requestRefreshPresentation({
      running: false,
      last_status: "skipped",
      last_warning: "Jellyseerr non risponde: refresh richieste saltato.",
      last_warning_at: "2026-08-12T09:15:22+00:00",
      last_error: null,
      completed_at: "2026-08-12T09:15:22+00:00",
    })).toMatchObject({
      label: "Saltato",
      severity: "warning",
      detail: "Jellyseerr non risponde: refresh richieste saltato.",
    });
    expect(formatConfigurationMoment("2026-08-12T09:15:22+00:00")).toMatch(/^12\/08\/2026, /);
    expect(formatConfigurationMoment("2026-08-12T09:15:22+00:00")).toMatch(/\d{2}:\d{2}:\d{2}/);
  });

  it("does not invent a completed state before the first request refresh", () => {
    expect(requestRefreshPresentation({
      running: false,
      last_status: null,
      last_warning: null,
      last_warning_at: null,
      last_error: null,
      completed_at: null,
    })).toMatchObject({ label: "Mai eseguito", severity: "neutral" });
  });

  it("separates an active refresh from a skipped refresh without warnings", () => {
    expect(requestRefreshPresentation({
      running: true,
      last_status: "running",
      last_warning: null,
      last_warning_at: null,
      last_error: null,
      completed_at: null,
    })).toMatchObject({ label: "In aggiornamento", severity: "info" });
    expect(requestRefreshPresentation({
      running: false,
      last_status: "skipped",
      last_warning: null,
      last_warning_at: null,
      last_error: null,
      completed_at: null,
    })).toMatchObject({ label: "Saltato", severity: "neutral" });
  });
});
