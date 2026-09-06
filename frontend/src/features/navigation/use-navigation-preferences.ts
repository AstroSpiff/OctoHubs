import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { saveNavigationPreferences } from "@/features/navigation/navigation-preferences-api";
import {
  persistNavigationPreferences,
  resolveNavigationPreferences,
  type NavigationPreferences,
} from "@/features/navigation/navigation-preferences";
import type { Session } from "@/lib/session";
import type { UiPreferencesRequest } from "@/lib/ui-api-contracts";
import { browserLocalStorage } from "@/lib/safe-web-storage";

function initialNavigationPreferences(): NavigationPreferences {
  return resolveNavigationPreferences(
    browserLocalStorage(),
  );
}

function useNavigationPreferences(serverPreferences?: NavigationPreferences) {
  const client = useQueryClient();
  const [preferences, setPreferences] = useState<NavigationPreferences>(initialNavigationPreferences);
  const preferencesRef = useRef(preferences);
  const mutationGenerationRef = useRef(0);
  const serverSignature = serverPreferences
    ? `${serverPreferences.primary_navigation}|${serverPreferences.secondary_navigation}`
    : "";

  const persistLocally = useCallback((next: NavigationPreferences) => {
    persistNavigationPreferences(next, browserLocalStorage());
  }, []);

  useEffect(() => {
    if (!serverPreferences) return;
    const next = resolveNavigationPreferences(browserLocalStorage(), serverPreferences);
    preferencesRef.current = next;
    setPreferences(next);
    persistLocally(next);
  }, [persistLocally, serverPreferences, serverSignature]);

  const mutation = useMutation({
    mutationFn: saveNavigationPreferences,
  });

  const updatePreferences = useCallback((partial: UiPreferencesRequest) => {
    const previous = preferencesRef.current;
    const next = { ...previous, ...partial };
    preferencesRef.current = next;
    setPreferences(next);
    persistLocally(next);
    const generation = mutationGenerationRef.current + 1;
    mutationGenerationRef.current = generation;
    mutation.mutate(partial, {
      onSuccess: (saved) => {
        if (generation !== mutationGenerationRef.current) return;
        const resolved = resolveNavigationPreferences(browserLocalStorage(), saved);
        preferencesRef.current = resolved;
        setPreferences(resolved);
        persistLocally(resolved);
        client.setQueryData<Session>(["session"], (current) => (
          current ? { ...current, preferences: resolved } : current
        ));
      },
      onError: () => {
        if (generation !== mutationGenerationRef.current) return;
        preferencesRef.current = previous;
        setPreferences(previous);
        persistLocally(previous);
      },
    });
  }, [client, mutation, persistLocally]);

  return {
    error: mutation.error,
    isSaving: mutation.isPending,
    preferences,
    updatePreferences,
  };
}

export { useNavigationPreferences };
