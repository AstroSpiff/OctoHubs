export type PrimaryNavigationMode = "top" | "sidebar";
export type SecondaryNavigationMode = "tabs" | "sidebar";

export type NavigationPreferences = {
  primary_navigation: PrimaryNavigationMode;
  secondary_navigation: SecondaryNavigationMode;
};

const navigationPreferencesStorageKey = "octohubs.navigation-preferences";

const defaultNavigationPreferences: NavigationPreferences = {
  primary_navigation: "top",
  secondary_navigation: "tabs",
};

function isPrimaryNavigationMode(value: unknown): value is PrimaryNavigationMode {
  return value === "top" || value === "sidebar";
}

function isSecondaryNavigationMode(value: unknown): value is SecondaryNavigationMode {
  return value === "tabs" || value === "sidebar";
}

function normalizeNavigationPreferences(value: unknown): NavigationPreferences {
  const source = value && typeof value === "object" ? value as Partial<NavigationPreferences> : {};
  return {
    primary_navigation: isPrimaryNavigationMode(source.primary_navigation)
      ? source.primary_navigation
      : defaultNavigationPreferences.primary_navigation,
    secondary_navigation: isSecondaryNavigationMode(source.secondary_navigation)
      ? source.secondary_navigation
      : defaultNavigationPreferences.secondary_navigation,
  };
}

function storedNavigationPreferences(storage: Pick<Storage, "getItem"> | null): NavigationPreferences | null {
  if (!storage) return null;
  const value = storage.getItem(navigationPreferencesStorageKey);
  if (!value) return null;
  try {
    return normalizeNavigationPreferences(JSON.parse(value));
  } catch {
    return null;
  }
}

function resolveNavigationPreferences(storage: Pick<Storage, "getItem"> | null, serverValue?: unknown): NavigationPreferences {
  if (serverValue) return normalizeNavigationPreferences(serverValue);
  return storedNavigationPreferences(storage) || defaultNavigationPreferences;
}

function persistNavigationPreferences(preferences: NavigationPreferences, storage: Pick<Storage, "setItem"> | null): void {
  storage?.setItem(navigationPreferencesStorageKey, JSON.stringify(preferences));
}

export {
  defaultNavigationPreferences,
  isPrimaryNavigationMode,
  isSecondaryNavigationMode,
  navigationPreferencesStorageKey,
  normalizeNavigationPreferences,
  persistNavigationPreferences,
  resolveNavigationPreferences,
  storedNavigationPreferences,
};
