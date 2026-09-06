import { request, setCsrfToken } from "@/lib/http";
import type { UiSessionResponse } from "@/lib/ui-api-contracts";

export type Session = Omit<UiSessionResponse, "ok">;

export async function getSession(): Promise<Session> {
  const payload = await request<UiSessionResponse>("/api/ui/session");
  setCsrfToken(payload.csrf_token);
  return payload;
}
