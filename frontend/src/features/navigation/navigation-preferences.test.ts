import { describe, expect, it } from "vitest";

import {
  defaultNavigationPreferences,
  navigationPreferencesStorageKey,
  normalizeNavigationPreferences,
  resolveNavigationPreferences,
  storedNavigationPreferences,
} from "@/features/navigation/navigation-preferences";

function memoryStorage(entries: Record<string, string> = {}) {
  return {
    getItem: (key: string) => entries[key] ?? null,
    setItem: (key: string, value: string) => {
      entries[key] = value;
    },
  };
}

describe("navigation preferences", () => {
  it("uses the compact top layout and contextual tabs by default", () => {
    expect(defaultNavigationPreferences).toEqual({
      primary_navigation: "top",
      secondary_navigation: "tabs",
    });
    expect(normalizeNavigationPreferences({ primary_navigation: "unknown", secondary_navigation: "aside" })).toEqual(defaultNavigationPreferences);
  });

  it("uses the server account choice before an older local fallback", () => {
    const storage = memoryStorage({
      [navigationPreferencesStorageKey]: JSON.stringify({ primary_navigation: "sidebar", secondary_navigation: "sidebar" }),
    });

    expect(storedNavigationPreferences(storage)).toEqual({ primary_navigation: "sidebar", secondary_navigation: "sidebar" });
    expect(resolveNavigationPreferences(storage, { primary_navigation: "top", secondary_navigation: "tabs" })).toEqual(defaultNavigationPreferences);
  });
});
