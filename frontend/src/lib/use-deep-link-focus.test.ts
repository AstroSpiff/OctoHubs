import { describe, expect, it } from "vitest";

import { deepLinkFocusId } from "@/lib/use-deep-link-focus";

describe("deep link focus", () => {
  it("reads only a named focus target from the URL query", () => {
    expect(deepLinkFocusId("?focus=configuration-database")).toBe("configuration-database");
    expect(deepLinkFocusId("?tab=services&focus=requests-refresh")).toBe("requests-refresh");
    expect(deepLinkFocusId("")).toBe("");
    expect(deepLinkFocusId("?focus=%20%20")).toBe("");
  });
});
