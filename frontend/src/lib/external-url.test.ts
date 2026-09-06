import { describe, expect, it } from "vitest";

import { safeExternalHttpUrl } from "@/lib/external-url";

describe("safeExternalHttpUrl", () => {
  it.each(["data:text/html,boom", "javascript:alert(1)", "file:///tmp/a", "https://u:p@example.test/x", "not a url"])(
    "rejects active or credential-bearing URL %s",
    (value) => expect(safeExternalHttpUrl(value)).toBeNull(),
  );

  it("keeps ordinary HTTP links", () => {
    expect(safeExternalHttpUrl("https://example.test/source?q=1")).toBe("https://example.test/source?q=1");
  });
});
