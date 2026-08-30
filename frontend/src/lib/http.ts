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

export function setCsrfToken(token: string) {
  csrfToken = token;
  csrfTokenRequest = null;
}

export function getCsrfToken() {
  return csrfToken;
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
        const payload = await response.json() as { csrf_token?: unknown };
        const token = typeof payload.csrf_token === "string" ? payload.csrf_token : "";
        if (!token) throw new ApiError("Token CSRF non disponibile", 403);
        csrfToken = token;
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
): Promise<Response> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD" && !headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", await ensureCsrfToken());
  }
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    const message = await readError(response);
    const canRetryCsrf =
      allowCsrfRetry &&
      method !== "GET" &&
      method !== "HEAD" &&
      response.status === 403 &&
      message === "CSRF token non valido";
    if (canRetryCsrf) {
      setCsrfToken("");
      return sendRequest(path, init, false);
    }
    if (response.status === 401 && window.location.pathname.startsWith("/app")) {
      const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
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
