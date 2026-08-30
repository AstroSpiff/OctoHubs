import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AccountMenu } from "@/components/account-menu";

describe("AccountMenu", () => {
  it("keeps interface preferences, theme control, and logout in one account menu", () => {
    const markup = renderToStaticMarkup(
      <AccountMenu
        roleLabel="Amministratore"
        theme="light"
        username="roy"
        onOpenPreferences={() => undefined}
        onToggleTheme={() => undefined}
      />,
    );

    expect(markup).toContain("Preferenze interfaccia");
    expect(markup).toContain("Attiva tema scuro");
    expect(markup).toContain('href="/logout"');
    expect(markup).toContain("Apri menu account di roy");
  });

  it("offers the inverse theme action when dark mode is active", () => {
    const markup = renderToStaticMarkup(
      <AccountMenu
        roleLabel="Utente"
        theme="dark"
        username="roy"
        onOpenPreferences={() => undefined}
        onToggleTheme={() => undefined}
      />,
    );

    expect(markup).toContain("Attiva tema chiaro");
  });

  it("keeps the compact trigger intentionally avatar-only", () => {
    const markup = renderToStaticMarkup(
      <AccountMenu
        compact
        roleLabel="Amministratore"
        theme="dark"
        username="admin"
        onOpenPreferences={() => undefined}
        onToggleTheme={() => undefined}
      />,
    );

    expect(markup).toContain("session-account-menu--compact");
    expect(markup).not.toContain('class="session-user"');
    expect(markup).not.toContain("session-account-menu-chevron");
  });
});
