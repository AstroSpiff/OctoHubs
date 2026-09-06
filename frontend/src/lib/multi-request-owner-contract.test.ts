import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const ownerBoundWorkflows = [
  "../features/users/api.ts",
  "../features/users/components/clone-user-dialog.tsx",
  "../features/collections/collection-save-flow.ts",
  "../features/probe/use-probe-data-actions.ts",
  "../features/navigation/use-persisted-tab-order.ts",
] as const;

describe("multi-request authenticated owner contract", () => {
  it.each(ownerBoundWorkflows)("keeps %s fenced to its initiating owner", (relativePath) => {
    const source = readFileSync(new URL(relativePath, import.meta.url), "utf8");

    expect(source).toContain("captureAuthenticatedActionOwner");
    expect(source).toContain("assertAuthenticatedActionOwner");
  });

  it("keeps the CSRF retry itself owner-bound", () => {
    const source = readFileSync(new URL("./http.ts", import.meta.url), "utf8");

    expect(source).toContain("return sendRequest(path, init, false, owner)");
    expect(source).toContain("assertAuthenticatedActionOwner(owner)");
  });
});
