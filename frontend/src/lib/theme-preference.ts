export type ApplicationTheme = "light" | "dark";

const themeStorageKey = "octohubs.theme";

type ThemeStorage = Pick<Storage, "getItem" | "setItem">;
type ThemeRoot = {
  dataset: { theme?: string };
  style: { colorScheme: string };
};

function isApplicationTheme(value: string | null): value is ApplicationTheme {
  return value === "light" || value === "dark";
}

function systemApplicationTheme(prefersDark: boolean): ApplicationTheme {
  return prefersDark ? "dark" : "light";
}

function storedApplicationTheme(storage: ThemeStorage | null): ApplicationTheme | null {
  if (!storage) return null;
  const value = storage.getItem(themeStorageKey);
  return isApplicationTheme(value) ? value : null;
}

function resolveApplicationTheme(storage: ThemeStorage | null, prefersDark: boolean): ApplicationTheme {
  return storedApplicationTheme(storage) || systemApplicationTheme(prefersDark);
}

function applyApplicationTheme(theme: ApplicationTheme, root: ThemeRoot): void {
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

function persistApplicationTheme(theme: ApplicationTheme, storage: ThemeStorage | null): void {
  storage?.setItem(themeStorageKey, theme);
}

function browserThemePreference(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function initializeApplicationTheme(): ApplicationTheme {
  const storage = typeof window === "undefined" ? null : window.localStorage;
  const root = typeof document === "undefined" ? null : document.documentElement;
  const theme = resolveApplicationTheme(storage, browserThemePreference());
  if (root) applyApplicationTheme(theme, root);
  return theme;
}

export {
  applyApplicationTheme,
  browserThemePreference,
  initializeApplicationTheme,
  persistApplicationTheme,
  resolveApplicationTheme,
  storedApplicationTheme,
  systemApplicationTheme,
  themeStorageKey,
};
