import type { NavigationPreferences } from "@/features/navigation/navigation-preferences";

type UiRole = "admin" | "user" | "viewer";

type UiSessionResponse = {
  ok: true;
  user: { id: number | null; username: string; email: string; role: UiRole };
  preferences: NavigationPreferences;
  csrf_token: string;
};

type UiPreferencesRequest =
  | {
      primary_navigation: NavigationPreferences["primary_navigation"];
      secondary_navigation?: NavigationPreferences["secondary_navigation"];
    }
  | {
      primary_navigation?: NavigationPreferences["primary_navigation"];
      secondary_navigation: NavigationPreferences["secondary_navigation"];
    };

type UiPreferencesResponse = {
  success: true;
  preferences: NavigationPreferences;
};

type UiTabOrderEntry = {
  tab_key: string;
  position: number;
};

type UiTabOrderRequest = {
  page: string;
  order: UiTabOrderEntry[];
};

type UiTabOrderResponse = {
  success: true;
  order: UiTabOrderEntry[];
};

export type {
  UiPreferencesRequest,
  UiPreferencesResponse,
  UiRole,
  UiSessionResponse,
  UiTabOrderEntry,
  UiTabOrderRequest,
  UiTabOrderResponse,
};
