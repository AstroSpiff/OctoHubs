import { useContext } from "react";

import { NavigationPreferencesContext } from "@/features/navigation/navigation-preferences-store";
import type { NavigationPreferencesState } from "@/features/navigation/navigation-preferences-store";

function useNavigationPreferencesContext(): NavigationPreferencesState {
  const value = useContext(NavigationPreferencesContext);
  if (!value) throw new Error("Navigation preferences are unavailable outside the app shell.");
  return value;
}

export { useNavigationPreferencesContext };
