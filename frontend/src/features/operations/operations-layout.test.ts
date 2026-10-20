import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "operations.css"), "utf8");
const appShellCss = readFileSync(
  join(__dirname, "../../styles/app-shell.css"),
  "utf8",
);
const usersOperationsCenter = readFileSync(
  join(__dirname, "../users/components/users-operations-center.tsx"),
  "utf8",
);
const operationsCenterView = readFileSync(
  join(__dirname, "components/operations-center-view.tsx"),
  "utf8",
);

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
}

describe("operations center layout", () => {
  it("keeps status badges content-sized and on one line", () => {
    const statusRule = rule(".operations-center-item-status .inline-flex");
    const actionsRule = rule(".operations-center-actions .inline-flex");

    expect(statusRule).toContain("width: auto");
    expect(statusRule).toContain("white-space: nowrap");
    expect(actionsRule).toContain("width: 30px");
    expect(actionsRule).not.toContain(".operations-center-item-status");
  });

  it("does not apply subtitle layout rules to status badges", () => {
    expect(css).toContain(
      ".operations-center-item-header > div:first-child > span",
    );
    expect(css).not.toContain(".operations-center-item-header span {");
  });

  it("uses the canonical operations toggle on the users page", () => {
    expect(usersOperationsCenter).not.toContain("operations-center--users");
    expect(css).not.toContain(".operations-center--users");
  });

  it("keeps the mobile operations center above the primary navigation", () => {
    expect(appShellCss).toContain("--mobile-primary-navigation-height: 68px");
    expect(css).toContain(
      "var(--mobile-primary-navigation-height) + 10px + env(safe-area-inset-bottom)",
    );
    expect(css).not.toContain(
      "bottom: max(10px, env(safe-area-inset-bottom))",
    );
    expect(css).toContain(
      "100dvh - var(--mobile-primary-navigation-height) - 20px - env(safe-area-inset-bottom)",
    );
    expect(css).toContain("grid-template-rows: minmax(0, 1fr) auto");
  });

  it("hides only the operations label on smartphones", () => {
    expect(operationsCenterView).toContain(
      'className="operations-center-toggle-label"',
    );
    expect(css).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?\.operations-center-toggle-label\s*\{\s*display: none;/,
    );
    expect(rule(".operations-center-toggle")).not.toContain("font-size: 0");
  });

  it("keeps the smartphone toggle anchored when the panel opens", () => {
    expect(css).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?\.operations-center-toggle\s*\{[\s\S]*?grid-row: 2;/,
    );
  });
});
