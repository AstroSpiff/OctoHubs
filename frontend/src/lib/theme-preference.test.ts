import { describe, expect, it } from "vitest";

import {
  applyApplicationTheme,
  persistApplicationTheme,
  resolveApplicationTheme,
  themeStorageKey,
} from "@/lib/theme-preference";

function createStorage(initialValue: string | null = null) {
  let value = initialValue;
  return {
    getItem: () => value,
    setItem: (_key: string, nextValue: string) => {
      value = nextValue;
    },
    value: () => value,
  };
}

describe("theme preference", () => {
  it("uses the system preference until the user has made a choice", () => {
    expect(resolveApplicationTheme(null, false)).toBe("light");
    expect(resolveApplicationTheme(null, true)).toBe("dark");
  });

  it("keeps a valid saved preference over the system preference", () => {
    expect(resolveApplicationTheme(createStorage("light"), true)).toBe("light");
    expect(resolveApplicationTheme(createStorage("dark"), false)).toBe("dark");
  });

  it("ignores invalid persisted values", () => {
    expect(resolveApplicationTheme(createStorage("violet"), true)).toBe("dark");
  });

  it("persists and applies the selected theme", () => {
    const storage = createStorage();
    const root: { dataset: { theme?: string }; style: { colorScheme: string } } = {
      dataset: {},
      style: { colorScheme: "" },
    };

    persistApplicationTheme("dark", storage);
    applyApplicationTheme("dark", root);

    expect(storage.value()).toBe("dark");
    expect(themeStorageKey).toBe("octohubs.theme");
    expect(root.dataset.theme).toBe("dark");
    expect(root.style.colorScheme).toBe("dark");
  });

  it("falls back to the system theme when storage reads fail", () => {
    const storage = {
      getItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
      setItem: () => undefined,
    };

    expect(resolveApplicationTheme(storage, true)).toBe("dark");
  });
});
