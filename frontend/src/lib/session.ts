import { request, setCsrfToken } from "@/lib/http";
import type { NavigationPreferences } from "@/features/navigation/navigation-preferences";

export type Session = {
  user: { id: number | null; username: string; email: string; role: string };
  preferences: NavigationPreferences;
  csrf_token: string;
};

export async function getSession(): Promise<Session> {
  const payload = await request<Session & { ok: boolean }>("/api/ui/session");
  setCsrfToken(payload.csrf_token);
  return payload;
}
