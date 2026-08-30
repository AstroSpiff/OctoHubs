import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { saveNavigationPreferences } from "@/features/navigation/navigation-preferences-api";
import {
  persistNavigationPreferences,
  resolveNavigationPreferences,
  type NavigationPreferences,
} from "@/features/navigation/navigation-preferences";
import type { Session } from "@/lib/session";

function initialNavigationPreferences(): NavigationPreferences {
  return resolveNavigationPreferences(
    typeof window === "undefined" ? null : window.localStorage,
  );
}

function useNavigationPreferences(serverPreferences?: NavigationPreferences) {
  const client = useQueryClient();
  const [preferences, setPreferences] = useState<NavigationPreferences>(initialNavigationPreferences);
  const preferencesRef = useRef(preferences);
  const serverSignature = serverPreferences
    ? `${serverPreferences.primary_navigation}|${serverPreferences.secondary_navigation}`
    : "";

  const persistLocally = useCallback((next: NavigationPreferences) => {
    persistNavigationPreferences(next, window.localStorage);
  }, []);

  useEffect(() => {
    if (!serverPreferences) return;
    const next = resolveNavigationPreferences(window.localStorage, serverPreferences);
    preferencesRef.current = next;
    setPreferences(next);
    persistLocally(next);
  }, [persistLocally, serverPreferences, serverSignature]);

  const mutation = useMutation({
    mutationFn: saveNavigationPreferences,
    onSuccess: (saved) => {
      const next = resolveNavigationPreferences(window.localStorage, saved);
      preferencesRef.current = next;
      setPreferences(next);
      persistLocally(next);
      client.setQueryData<Session>(["session"], (current) => (
        current ? { ...current, preferences: next } : current
      ));
    },
  });

  const updatePreferences = useCallback((partial: Partial<NavigationPreferences>) => {
    const previous = preferencesRef.current;
    const next = { ...previous, ...partial };
    preferencesRef.current = next;
    setPreferences(next);
    persistLocally(next);
    mutation.mutate(next, {
      onError: () => {
        preferencesRef.current = previous;
        setPreferences(previous);
        persistLocally(previous);
      },
    });
  }, [mutation, persistLocally]);

  return {
    error: mutation.error,
    isSaving: mutation.isPending,
    preferences,
    updatePreferences,
  };
}

export { useNavigationPreferences };
