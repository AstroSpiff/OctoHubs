import { describe, expect, it } from "vitest";

import {
  readLatestDisplayLimit,
  saveLatestDisplayLimit,
} from "@/features/emby-latest/latest-display-preferences";

function memoryStorage(entries: Record<string, string> = {}) {
  const values = new Map(Object.entries(entries));
  return {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  };
}

describe("latest display preferences", () => {
  it("uses the saved valid display limit", () => {
    expect(
      readLatestDisplayLimit(
        memoryStorage({ octohubs_latest_display_limit: "50" }),
      ),
    ).toBe(50);
  });

  it("falls back cleanly for an invalid saved value", () => {
    const storage = memoryStorage({ octohubs_latest_display_limit: "15" });
    saveLatestDisplayLimit(15, storage);

    expect(readLatestDisplayLimit(storage)).toBe(10);
    expect(storage.getItem("octohubs_latest_display_limit")).toBe("15");
  });
});
