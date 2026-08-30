import { describe, expect, it } from "vitest";

import { telegramAlertPresentation } from "@/features/configuration/telegram-preset-presentation";

describe("telegram preset presentation", () => {
  it("makes a bot administrator immediately recognizable", () => {
    expect(telegramAlertPresentation({ status: "admin", message: "Bot admin" })).toEqual({ label: "Bot admin", severity: "ok", detail: "Bot admin" });
  });

  it("keeps missing and unverified destinations distinct", () => {
    expect(telegramAlertPresentation({ status: "missing" }).severity).toBe("error");
    expect(telegramAlertPresentation(undefined)).toEqual({ label: "Non verificato", severity: "unknown", detail: "Nessuna verifica disponibile" });
  });
});
