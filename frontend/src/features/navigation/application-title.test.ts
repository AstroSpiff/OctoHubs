import { describe, expect, it } from "vitest";

import { applicationTitle } from "@/features/navigation/application-title";

describe("applicationTitle", () => {
  it("uses the most specific title for nested workspace routes", () => {
    expect(applicationTitle("/transcode-guard/rules")).toBe(
      "Regole Transcode Guard | OctoHubs",
    );
    expect(applicationTitle("/users/icons")).toBe("Icone utenti | OctoHubs");
  });

  it("keeps the product name for an unknown route", () => {
    expect(applicationTitle("/missing")).toBe("OctoHubs");
  });
});
