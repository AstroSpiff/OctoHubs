import { navigateBrowser, type BrowserEffectGuard } from "@/lib/browser-download";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let csrfToken = "";
let csrfTokenRequest: Promise<string> | null = null;
let sessionOwnerId: number | null = null;
let sessionOwnerGeneration = 0;

type AuthenticatedActionOwner = Readonly<{
  ownerId: number | null;
  generation: number;
}>;

export class SessionOwnerChangedError extends Error {
  constructor() {
    super("La sessione è cambiata durante l'operazione. Riprova con l'account corrente.");
    this.name = "SessionOwnerChangedError";
  }
}

export function setCsrfToken(token: string, ownerId?: number | null) {
  csrfToken = token;
  csrfTokenRequest = null;
  if (ownerId !== undefined && ownerId !== sessionOwnerId) {
    sessionOwnerId = ownerId;
    sessionOwnerGeneration += 1;
  } else if (!token && ownerId === undefined && sessionOwnerId !== null) {
    // Explicit resets (logout and test isolation) invalidate pending owners.
    sessionOwnerId = null;
    sessionOwnerGeneration += 1;
  }
}

export function getCsrfToken() {
  return csrfToken;
}

export function captureAuthenticatedActionOwner(): AuthenticatedActionOwner {
  return { ownerId: sessionOwnerId, generation: sessionOwnerGeneration };
}

export function assertAuthenticatedActionOwner(owner: AuthenticatedActionOwner): void {
  if (
    owner.ownerId !== sessionOwnerId
    || owner.generation !== sessionOwnerGeneration
  ) {
    throw new SessionOwnerChangedError();
  }
}

function authenticatedBrowserEffectGuard(owner: AuthenticatedActionOwner): BrowserEffectGuard {
  return { assertCurrent: () => assertAuthenticatedActionOwner(owner) };
}

function clearCsrfTokenForRetry() {
  csrfToken = "";
  csrfTokenRequest = null;
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = await response.json() as unknown;
    return errorMessageFromPayload(payload) || fallbackErrorMessage(response);
  } catch {
    return fallbackErrorMessage(response);
  }
}

function errorMessageFromPayload(payload: unknown): string {
  if (typeof payload === "string") return payload.trim();
  if (!isRecord(payload)) return "";

  return [payload.detail, payload.error, payload.message]
    .map(errorDetailMessage)
    .find(Boolean) || "";
}

function errorDetailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail.trim();
  if (Array.isArray(detail)) {
    return detail.map(errorDetailMessage).filter(Boolean).join("; ");
  }
  if (!isRecord(detail)) return "";

  const message = errorDetailMessage(detail.msg) || errorDetailMessage(detail.message);
  if (!message) return "";
  const location = validationLocation(detail.loc);
  return location ? `${location}: ${message}` : message;
}

function validationLocation(location: unknown): string {
  if (!Array.isArray(location)) return "";
  const parts = location.filter(
    (part): part is string | number =>
      typeof part === "string" || typeof part === "number",
  );
  if (["body", "query", "path", "header", "cookie"].includes(String(parts[0]))) {
    parts.shift();
  }
  return parts.join(".");
}

function fallbackErrorMessage(response: Response) {
  return response.statusText.trim() || `Errore HTTP ${response.status}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

async function ensureCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  if (!csrfTokenRequest) {
    csrfTokenRequest = fetch("/api/ui/session", { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) throw new ApiError(await readError(response), response.status);
        const payload = await response.json() as {
          csrf_token?: unknown;
          user?: { id?: unknown };
        };
        const token = typeof payload.csrf_token === "string" ? payload.csrf_token : "";
        if (!token) throw new ApiError("Token CSRF non disponibile", 403);
        const ownerId = typeof payload.user?.id === "number" ? payload.user.id : undefined;
        setCsrfToken(token, ownerId);
        return token;
      })
      .finally(() => {
        csrfTokenRequest = null;
      });
  }
  return csrfTokenRequest;
}

async function sendRequest(
  path: string,
  init: RequestInit = {},
  allowCsrfRetry = true,
  originalOwner?: AuthenticatedActionOwner,
): Promise<Response> {
  const method = (init.method || "GET").toUpperCase();
  const mutation = method !== "GET" && method !== "HEAD";
  let owner = originalOwner || captureAuthenticatedActionOwner();
  const headers = new Headers(init.headers);
  if (mutation && !headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", await ensureCsrfToken());
    if (owner.ownerId === null) owner = captureAuthenticatedActionOwner();
  }
  if (mutation) assertAuthenticatedActionOwner(owner);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    const message = await readError(response);
    const canRetryCsrf =
      allowCsrfRetry &&
      mutation &&
      response.status === 403 &&
      message === "CSRF token non valido";
    if (canRetryCsrf) {
      clearCsrfTokenForRetry();
      return sendRequest(path, init, false, owner);
    }
    if (response.status === 401 && window.location.pathname.startsWith("/app")) {
      const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      navigateBrowser(
        `/login?next=${encodeURIComponent(next)}`,
        authenticatedBrowserEffectGuard(owner),
      );
    }
    throw new ApiError(message, response.status);
  }
  return response;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await sendRequest(path, init)).json() as Promise<T>;
}

export async function requestBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  return (await sendRequest(path, init)).blob();
}

export type { AuthenticatedActionOwner };
