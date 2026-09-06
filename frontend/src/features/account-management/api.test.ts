import { afterEach, describe, expect, it, vi } from "vitest";

import { logoutCurrentSession } from "@/features/account-management/api";
import { setCsrfToken } from "@/lib/http";

describe("account session API", () => {
  afterEach(() => {
    setCsrfToken("");
    vi.unstubAllGlobals();
  });

  it("logs out with POST and the current CSRF token", async () => {
    setCsrfToken("csrf");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, redirect: "/login" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const redirect = await logoutCurrentSession();

    const [path, options] = fetchMock.mock.calls[0];
    expect(path).toBe("/logout");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("same-origin");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe("csrf");
    expect(redirect).toBe("/login");
  });
});
