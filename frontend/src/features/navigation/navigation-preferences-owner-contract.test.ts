import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("navigation preferences owner contract", () => {
  it("binds the open dialog and mutation status to the current owner", () => {
    const shell = readFileSync(new URL("../../components/app-shell.tsx", import.meta.url), "utf8");
    const preferences = readFileSync(new URL("./use-navigation-preferences.ts", import.meta.url), "utf8");

    expect(shell).toContain("useOwnerBoundDisclosure(currentOwnerKey)");
    expect(shell).toContain("open={preferencesDialog.isOpen}");
    expect(preferences).toContain("resetMutation()");
    expect(preferences).toContain("mutationGenerationRef.current += 1");
  });
});
