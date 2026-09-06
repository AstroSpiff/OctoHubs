import { afterEach, describe, expect, it, vi } from "vitest";

import { IconBindingsPartialError, saveIconBindings } from "@/features/user-icons/use-user-icons";
import { setCsrfToken } from "@/lib/http";

describe("icon binding fan-out outcomes", () => {
  afterEach(() => {
    setCsrfToken("");
    vi.unstubAllGlobals();
  });

  it("retains the exact failed target", async () => {
    setCsrfToken("csrf");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "failed b" }), { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);
    const inputs = [
      { targetType: "user" as const, targetId: "green:a", profileId: "p" },
      { targetType: "user" as const, targetId: "green:b", profileId: "p" },
    ];

    await expect(saveIconBindings(inputs)).rejects.toMatchObject({
      name: "IconBindingsPartialError",
      failedInputs: [inputs[1]],
    } satisfies Partial<IconBindingsPartialError>);
  });
});
