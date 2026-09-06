import { afterEach, describe, expect, it, vi } from "vitest";

import { getTabOrder, saveTabOrder } from "@/features/navigation/tab-order-api";
import { setCsrfToken } from "@/lib/http";

describe("tab order API contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken("");
  });

  it("round-trips the documented page and positioned order shape", async () => {
    setCsrfToken("csrf");
    const fixture = {
      success: true,
      order: [
        { tab_key: "operations", position: 0 },
        { tab_key: "probe", position: 1 },
      ],
    } as const;
    const fetchMock = vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify(fixture), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getTabOrder("primary")).resolves.toEqual(fixture.order);
    await saveTabOrder("primary", [...fixture.order]);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/ui/tab-order?page=primary");
    const [, options] = fetchMock.mock.calls[1];
    expect(JSON.parse(String(options.body))).toEqual({
      page: "primary",
      order: fixture.order,
    });
  });
});
