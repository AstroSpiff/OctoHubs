import { describe, expect, it } from "vitest";

import { tabAtKey } from "@/components/ui/tab-navigation";

describe("tab navigation", () => {
  const tabs = ["queue", "history", "errors", "incomplete"] as const;

  it("moves through tabs with arrow keys and wraps at the ends", () => {
    expect(tabAtKey(tabs, "queue", "ArrowLeft")).toBe("incomplete");
    expect(tabAtKey(tabs, "incomplete", "ArrowRight")).toBe("queue");
    expect(tabAtKey(tabs, "history", "ArrowDown")).toBe("errors");
  });

  it("supports Home and End without handling unrelated keys", () => {
    expect(tabAtKey(tabs, "errors", "Home")).toBe("queue");
    expect(tabAtKey(tabs, "errors", "End")).toBe("incomplete");
    expect(tabAtKey(tabs, "errors", "Enter")).toBeUndefined();
  });
});
