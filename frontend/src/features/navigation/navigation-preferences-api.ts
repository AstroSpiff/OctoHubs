import { request } from "@/lib/http";

import type { NavigationPreferences } from "@/features/navigation/navigation-preferences";

type NavigationPreferencesResponse = {
  success?: boolean;
  preferences?: NavigationPreferences;
};

async function saveNavigationPreferences(preferences: NavigationPreferences): Promise<NavigationPreferences> {
  const response = await request<NavigationPreferencesResponse>("/api/ui/preferences", {
    method: "PUT",
    body: JSON.stringify(preferences),
  });
  if (response.success === false || !response.preferences) {
    throw new Error("Risposta preferenze interfaccia non valida");
  }
  return response.preferences;
}

export { saveNavigationPreferences };
