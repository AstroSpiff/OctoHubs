import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "guard-settings.css"), "utf8");
const globalSource = readFileSync(
  join(__dirname, "components/guard-settings-global.tsx"),
  "utf8",
);
const workspaceSource = readFileSync(
  join(__dirname, "components/guard-settings-workspace.tsx"),
  "utf8",
);

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`(?:^|})\\s*${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
}

describe("Transcode Guard global settings layout", () => {
  it("uses the available desktop width without pushing the fields to the right", () => {
    const global = rule(".guard-settings-global");
    const fields = rule(".guard-settings-global-fields");

    expect(css).toMatch(
      /\.guard-settings-editable\s*\{[^}]*container-name:\s*guard-settings-editor;[^}]*container-type:\s*inline-size;/,
    );
    expect(global).toContain(
      "grid-template-columns: minmax(240px, 1fr) auto minmax(480px, 1.25fr)",
    );
    expect(fields).toContain("repeat(2, minmax(220px, 1fr))");
    expect(fields).not.toContain("justify-content: end");
  });

  it("reflows from a full-width field row to one column from the actual panel width", () => {
    expect(css).toMatch(
      /@container guard-settings-editor \(max-width: 1050px\)[\s\S]*?\.guard-settings-global-fields\s*\{[^}]*grid-column:\s*1 \/ -1;[^}]*grid-template-columns:\s*repeat\(2, minmax\(220px, 1fr\)\);/,
    );
    expect(css).toMatch(
      /@container guard-settings-editor \(max-width: 620px\)[\s\S]*?\.guard-settings-global-fields\s*\{\s*grid-template-columns:\s*1fr;/,
    );
  });

  it("explains the monitor and the rule precedence in concrete terms", () => {
    expect(globalSource).toContain(
      "Reagisce agli eventi Emby; l'intervallo recupera quelli eventualmente persi.",
    );
    expect(globalSource).toContain("secondi, controllo di recupero");
    expect(workspaceSource).toContain(
      "scegli se registrare, avvisare l&apos;utente o fermare gli stream",
    );
    expect(workspaceSource).toContain("La prima regola valida ha precedenza.");
  });
});
