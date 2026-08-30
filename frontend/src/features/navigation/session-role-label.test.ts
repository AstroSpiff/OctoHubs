import { describe, expect, it } from "vitest";

import { sessionRoleLabel } from "@/features/navigation/session-role-label";

describe("sessionRoleLabel", () => {
  it("translates every role supported by the authentication backend", () => {
    expect(sessionRoleLabel("admin")).toBe("Amministratore");
    expect(sessionRoleLabel("user")).toBe("Utente");
    expect(sessionRoleLabel("viewer")).toBe("Sola lettura");
  });

  it("keeps unknown values readable and handles a missing session role", () => {
    expect(sessionRoleLabel(" operator ")).toBe("operator");
    expect(sessionRoleLabel()).toBe("Verifica sessione");
  });
});
