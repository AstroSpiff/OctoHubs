import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PasswordDialog } from "@/features/users/components/password-dialog";

describe("PasswordDialog", () => {
  it("keeps the group reset and alignment actions visible in the password workflow", () => {
    const markup = renderToStaticMarkup(
      <PasswordDialog
        target={{ scope: "group", groupId: "group-1", name: "Famiglia", mismatchCount: 2 }}
        saving={false}
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );

    expect(markup).toContain("2 utenti non allineati");
    expect(markup).toContain("Reimposta");
    expect(markup).toContain("Aggiorna password");
    expect(markup).toContain("Mostra password");
  });

  it("shows the Emby and alignment state when managing an individual password", () => {
    const markup = renderToStaticMarkup(
      <PasswordDialog
        target={{ scope: "user", serverId: "green", userId: "user-1", name: "Roy", hasEmbyPassword: true, mismatch: true }}
        saving={false}
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );

    expect(markup).toContain("Emby: presente");
  });

  it("renders mutation failures inside the active modal", () => {
    const markup = renderToStaticMarkup(
      <PasswordDialog
        target={{ scope: "group", groupId: "group-1", name: "Famiglia" }}
        saving={false}
        mutationError="Aggiornamento non riuscito"
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );

    expect(markup).toContain('role="alert"');
    expect(markup).toContain("Aggiornamento non riuscito");
  });
});
