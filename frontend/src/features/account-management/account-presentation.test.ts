import { describe, expect, it } from "vitest";

import { accountRoleLabels, apiTokenScopeLabels, formatAccountDate, formatApiTokenAction, navigationPreferenceLabels } from "@/features/account-management/account-presentation";

describe("account presentation", () => {
  it("uses concrete labels for each OctoHubs access role", () => {
    expect(accountRoleLabels).toEqual({
      admin: "Amministratore",
      user: "Operatore",
      viewer: "Sola lettura",
    });
  });

  it("describes only the personal workspace layout choices", () => {
    expect(navigationPreferenceLabels({ primary_navigation: "sidebar", secondary_navigation: "tabs" })).toEqual({
      primary: "A sinistra",
      secondary: "Tab orizzontali",
    });
  });

  it("uses readable labels for external API token scopes", () => {
    expect(apiTokenScopeLabels["read:status"]).toBe("Legge stato");
    expect(apiTokenScopeLabels["read:libraries"]).toBe("Legge librerie");
    expect(apiTokenScopeLabels["read:research"]).toBe("Legge ricerca");
    expect(apiTokenScopeLabels["read:publications"]).toBe("Legge pubblicazioni");
    expect(apiTokenScopeLabels["write:libraries"]).toBe("Modifica librerie");
    expect(apiTokenScopeLabels["write:research"]).toBe("Modifica ricerca");
    expect(apiTokenScopeLabels["write:publications"]).toBe("Modifica pubblicazioni");
    expect(apiTokenScopeLabels["write:event_bridge"]).toBe("Modifica Event Bridge");
    expect(apiTokenScopeLabels["admin:all"]).toBe("Amministrazione completa");
  });

  it("handles account activity dates without exposing raw timestamps", () => {
    expect(formatAccountDate(null)).toBe("Mai");
    expect(formatAccountDate("not-a-date")).toBe("Non disponibile");
    expect(formatAccountDate("2026-08-16T10:20:00+00:00")).toContain("2026");
  });

  it("summarizes API token audit actions without raw JSON", () => {
    expect(formatApiTokenAction(null)).toBe("Nessuna azione registrata");
    expect(formatApiTokenAction({
      action: "api_token_denied",
      at: "2026-08-16T10:20:00+00:00",
      method: "POST",
      path: "/api/telegram/action",
      required_scope: "write:configuration",
      result: "denied",
    })).toContain("Rifiutato: POST /api/telegram/action");
  });
});
