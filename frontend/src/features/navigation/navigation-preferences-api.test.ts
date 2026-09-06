import { afterEach, describe, expect, it, vi } from "vitest";

import { saveNavigationPreferences } from "@/features/navigation/navigation-preferences-api";
import { setCsrfToken } from "@/lib/http";

describe("navigation preferences API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken("");
  });

  it("sends only the field changed by the current tab", async () => {
    setCsrfToken("csrf");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      success: true,
      preferences: { primary_navigation: "sidebar", secondary_navigation: "tabs" },
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await saveNavigationPreferences({ primary_navigation: "sidebar" });

    const [, options] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(options.body))).toEqual({ primary_navigation: "sidebar" });
  });
});
