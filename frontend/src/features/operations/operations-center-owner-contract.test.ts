import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("operations center owner contract", () => {
  it("keys the global operations workflow to the authenticated owner", () => {
    const shell = readFileSync(
      new URL("../../components/app-shell.tsx", import.meta.url),
      "utf8",
    );

    expect(shell).toContain("<WorkspaceCapabilitiesProvider accountId={accountId} canMutate>");
    expect(shell).toContain("<OperationsCenter key={currentOwnerKey} />");
  });
});
