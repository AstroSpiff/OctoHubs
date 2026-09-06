import { request } from "@/lib/http";

import type { UiPreferencesRequest, UiPreferencesResponse } from "@/lib/ui-api-contracts";

async function saveNavigationPreferences(preferences: UiPreferencesRequest): Promise<UiPreferencesResponse["preferences"]> {
  const payload = preferences;
  const response = await request<UiPreferencesResponse>("/api/ui/preferences", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!response.preferences) {
    throw new Error("Risposta preferenze interfaccia non valida");
  }
  return response.preferences;
}

export { saveNavigationPreferences };
