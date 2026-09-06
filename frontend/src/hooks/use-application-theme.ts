import { useCallback, useState } from "react";

import {
  applyApplicationTheme,
  browserThemePreference,
  persistApplicationTheme,
  resolveApplicationTheme,
  type ApplicationTheme,
} from "@/lib/theme-preference";
import { browserLocalStorage } from "@/lib/safe-web-storage";

function initialApplicationTheme(): ApplicationTheme {
  return resolveApplicationTheme(browserLocalStorage(), browserThemePreference());
}

function useApplicationTheme() {
  const [theme, setTheme] = useState<ApplicationTheme>(initialApplicationTheme);

  const updateTheme = useCallback((nextTheme: ApplicationTheme) => {
    applyApplicationTheme(nextTheme, document.documentElement);
    persistApplicationTheme(nextTheme, browserLocalStorage());
    setTheme(nextTheme);
  }, []);

  const toggleTheme = useCallback(() => {
    updateTheme(theme === "light" ? "dark" : "light");
  }, [theme, updateTheme]);

  return { theme, toggleTheme, updateTheme };
}

export { useApplicationTheme };
