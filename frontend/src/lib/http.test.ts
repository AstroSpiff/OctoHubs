// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, SessionOwnerChangedError, request, setCsrfToken } from "@/lib/http";

describe("HTTP client CSRF handling", () => {
  afterEach(() => {
    setCsrfToken("");
    vi.unstubAllGlobals();
  });

  it("loads the session token before the first mutation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: "fresh-token" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await request<{ ok: boolean }>("/api/emby/probe/retry", { method: "POST", body: "{}" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/ui/session", { credentials: "same-origin" });
    const [, options] = fetchMock.mock.calls[1];
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe("fresh-token");
  });

  it("reuses an already available token without another session request", async () => {
    setCsrfToken("known-token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await request<{ ok: boolean }>("/api/emby/probe/retry", { method: "POST", body: "{}" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, options] = fetchMock.mock.calls[0];
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe("known-token");
  });

  it("refreshes a stale CSRF token once without retrying unrelated forbidden responses", async () => {
    setCsrfToken("stale-token");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "CSRF token non valido" }), { status: 403 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: "renewed-token" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await request<{ ok: boolean }>("/api/emby/probe/retry", { method: "POST", body: "{}" });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const [, firstOptions] = fetchMock.mock.calls[0];
    const [, retryOptions] = fetchMock.mock.calls[2];
    expect(new Headers(firstOptions.headers).get("X-CSRF-Token")).toBe("stale-token");
    expect(new Headers(retryOptions.headers).get("X-CSRF-Token")).toBe("renewed-token");
  });

  it("never retries a mutation under a different authenticated owner", async () => {
    setCsrfToken("csrf-a", 1);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "CSRF token non valido" }), { status: 403 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: "csrf-b", user: { id: 2 } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      request("/api/ui/preferences", { method: "PUT", body: "{}" }),
    ).rejects.toBeInstanceOf(SessionOwnerChangedError);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/ui/preferences",
      "/api/ui/session",
    ]);
  });

  it("does not redirect a stale 401 response after the authenticated owner changes", async () => {
    setCsrfToken("csrf-a", 1);
    window.history.replaceState({}, "", "/app/research?tab=requests#pending");
    let resolveResponse!: (response: Response) => void;
    const response = new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(() => response));

    const staleRequest = request("/api/stale-owner");
    setCsrfToken("csrf-b", 2);
    resolveResponse(new Response(JSON.stringify({ detail: "Sessione scaduta" }), { status: 401 }));

    await expect(staleRequest).rejects.toBeInstanceOf(SessionOwnerChangedError);
    expect(window.location.pathname).toBe("/app/research");
    expect(window.location.search).toBe("?tab=requests");
    expect(window.location.hash).toBe("#pending");
  });
});

describe("HTTP error messages", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves a string detail", async () => {
    stubErrorResponse({ detail: "Configurazione non valida" }, 422);

    await expect(request("/api/test")).rejects.toEqual(
      new ApiError("Configurazione non valida", 422),
    );
  });

  it("aggregates FastAPI validation issues with their field locations", async () => {
    stubErrorResponse({
      detail: [
        { loc: ["body", "profile", "email"], msg: "Field required", type: "missing" },
        { loc: ["body", "items", 0, "enabled"], msg: "Input should be a valid boolean", type: "bool_parsing" },
      ],
    }, 422);

    await expect(request("/api/test")).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "profile.email: Field required; items.0.enabled: Input should be a valid boolean",
    });
  });

  it("extracts a message from an object detail without stringifying it", async () => {
    stubErrorResponse({
      detail: { loc: ["query", "server_id"], message: "Server sconosciuto" },
    }, 422);

    await expect(request("/api/test")).rejects.toMatchObject({
      message: "server_id: Server sconosciuto",
    });
  });

  it("uses a stable HTTP fallback for unknown objects and non-JSON bodies", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "invalid" } }), {
        status: 422,
        statusText: "Unprocessable Content",
      }))
      .mockResolvedValueOnce(new Response("upstream offline", {
        status: 502,
        statusText: "Bad Gateway",
      }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/api/unknown-error")).rejects.toMatchObject({
      message: "Unprocessable Content",
    });
    await expect(request("/api/non-json-error")).rejects.toMatchObject({
      message: "Bad Gateway",
    });
  });
});

function stubErrorResponse(payload: unknown, status: number) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), { status }),
  ));
}
