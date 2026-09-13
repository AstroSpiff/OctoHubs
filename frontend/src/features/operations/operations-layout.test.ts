import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "operations.css"), "utf8");
const usersOperationsCenter = readFileSync(
  join(__dirname, "../users/components/users-operations-center.tsx"),
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

  it("uses the canonical operations toggle on the users page", () => {
    expect(usersOperationsCenter).not.toContain("operations-center--users");
    expect(css).not.toContain(".operations-center--users");
  });
});
