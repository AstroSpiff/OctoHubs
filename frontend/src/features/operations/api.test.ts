import { afterEach, describe, expect, it, vi } from "vitest";

import { stopWorkflow } from "@/features/operations/api";
import { setCsrfToken } from "@/lib/http";

describe("workflow stop API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken("");
  });

  it("sends the immutable operation target", async () => {
    setCsrfToken("csrf-a", 1);
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ success: true, message: "Interruzione richiesta" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await stopWorkflow("operation-x");

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({ operation_id: "operation-x" });
  });
});
