import { createContext } from "react";

import type { useNavigationPreferences } from "@/features/navigation/use-navigation-preferences";

type NavigationPreferencesState = ReturnType<typeof useNavigationPreferences>;

const NavigationPreferencesContext = createContext<NavigationPreferencesState | null>(null);

export { NavigationPreferencesContext };
export type { NavigationPreferencesState };
