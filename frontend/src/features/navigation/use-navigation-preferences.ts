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

function useNavigationPreferences(
  serverPreferences: NavigationPreferences | undefined,
  accountId: number | null,
) {
  const client = useQueryClient();
  const [ownedPreferences, setOwnedPreferences] = useState(() => ({
    accountId,
    preferences: initialNavigationPreferences(),
  }));
  const preferences = ownedPreferences.accountId === accountId
    ? ownedPreferences.preferences
    : resolveNavigationPreferences(browserLocalStorage(), serverPreferences);
  const preferencesRef = useRef(preferences);
  preferencesRef.current = preferences;
  const accountIdRef = useRef(accountId);
  accountIdRef.current = accountId;
  const mutationGenerationRef = useRef(0);
  const serverSignature = serverPreferences
    ? `${serverPreferences.primary_navigation}|${serverPreferences.secondary_navigation}`
    : "";
  const mutation = useMutation({
    mutationFn: saveNavigationPreferences,
  });
  const resetMutation = mutation.reset;

  const persistLocally = useCallback((next: NavigationPreferences) => {
    persistNavigationPreferences(next, browserLocalStorage());
  }, []);

  useEffect(() => {
    if (!serverPreferences) return;
    const next = resolveNavigationPreferences(browserLocalStorage(), serverPreferences);
    preferencesRef.current = next;
    setOwnedPreferences({ accountId, preferences: next });
    persistLocally(next);
  }, [accountId, persistLocally, serverPreferences, serverSignature]);

  useEffect(() => {
    mutationGenerationRef.current += 1;
    resetMutation();
    if (!serverPreferences) {
      const next = resolveNavigationPreferences(browserLocalStorage());
      preferencesRef.current = next;
      setOwnedPreferences({ accountId, preferences: next });
    }
  }, [accountId, resetMutation, serverPreferences]);

  const updatePreferences = useCallback((partial: UiPreferencesRequest) => {
    const ownerId = accountIdRef.current;
    const previous = preferencesRef.current;
    const next = { ...previous, ...partial };
    preferencesRef.current = next;
    setOwnedPreferences({ accountId: ownerId, preferences: next });
    persistLocally(next);
    const generation = mutationGenerationRef.current + 1;
    mutationGenerationRef.current = generation;
    mutation.mutate(partial, {
      onSuccess: (saved) => {
        if (generation !== mutationGenerationRef.current || ownerId !== accountIdRef.current) return;
        const resolved = resolveNavigationPreferences(browserLocalStorage(), saved);
        preferencesRef.current = resolved;
        setOwnedPreferences({ accountId: ownerId, preferences: resolved });
        persistLocally(resolved);
        client.setQueryData<Session>(["session"], (current) => (
          current?.user.id === ownerId ? { ...current, preferences: resolved } : current
        ));
      },
      onError: () => {
        if (generation !== mutationGenerationRef.current || ownerId !== accountIdRef.current) return;
        preferencesRef.current = previous;
        setOwnedPreferences({ accountId: ownerId, preferences: previous });
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
