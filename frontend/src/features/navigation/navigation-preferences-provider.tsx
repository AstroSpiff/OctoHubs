import type { ReactNode } from "react";

import { NavigationPreferencesContext } from "@/features/navigation/navigation-preferences-store";
import type { NavigationPreferencesState } from "@/features/navigation/navigation-preferences-store";

function NavigationPreferencesProvider({ value, children }: { value: NavigationPreferencesState; children: ReactNode }) {
  return <NavigationPreferencesContext.Provider value={value}>{children}</NavigationPreferencesContext.Provider>;
}

export { NavigationPreferencesProvider };
