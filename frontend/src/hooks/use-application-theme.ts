import { useCallback, useState } from "react";

import {
  applyApplicationTheme,
  browserThemePreference,
  persistApplicationTheme,
  resolveApplicationTheme,
  type ApplicationTheme,
} from "@/lib/theme-preference";

function initialApplicationTheme(): ApplicationTheme {
  return resolveApplicationTheme(window.localStorage, browserThemePreference());
}

function useApplicationTheme() {
  const [theme, setTheme] = useState<ApplicationTheme>(initialApplicationTheme);

  const updateTheme = useCallback((nextTheme: ApplicationTheme) => {
    applyApplicationTheme(nextTheme, document.documentElement);
    persistApplicationTheme(nextTheme, window.localStorage);
    setTheme(nextTheme);
  }, []);

  const toggleTheme = useCallback(() => {
    updateTheme(theme === "light" ? "dark" : "light");
  }, [theme, updateTheme]);

  return { theme, toggleTheme, updateTheme };
}

export { useApplicationTheme };
