import { afterEach, describe, expect, it, vi } from "vitest";

import { createUsers, requireCompleteUserAction, toggleDownloadAccess, toggleRemoteAccess } from "@/features/users/api";
import { setCsrfToken } from "@/lib/http";

describe("user mutation outcomes", () => {
  afterEach(() => {
    setCsrfToken("");
    vi.unstubAllGlobals();
  });

  it("rejects HTTP-200 partial outcomes with the target journal", () => {
    expect(() => requireCompleteUserAction({
      ok: false,
      status: "partial",
      created: [{ user_id: "already-created" }],
      failed: [{ username: "alice", server_id: "green", stage: "identity", error: "ID non disponibile" }],
      reconciliation_required: true,
    }, "Creazione utenti")).toThrow("alice / green / identity: ID non disponibile");
  });

  it("accepts a complete mutation", () => {
    expect(requireCompleteUserAction({ ok: true, status: "success", failed: [] }, "Test").ok).toBe(true);
  });

  it("rejects an actual HTTP-200 create partial so onSuccess cannot close the dialog", async () => {
    setCsrfToken("csrf");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      ok: false,
      result: {
        status: "partial",
        created: [{ server_id: "green", user_id: "id-a" }],
        failed: [{ server_id: "blue", username: "alice", error: "offline" }],
        reconciliation_required: true,
      },
    }), { status: 200 })));

    await expect(createUsers({
      username: "alice",
      password: "",
      serverIds: ["green", "blue"],
      linkGroup: false,
    })).rejects.toThrow("alice / blue: offline");
  });

  it.each([
    ["remote", toggleRemoteAccess],
    ["download", toggleDownloadAccess],
  ])("rejects an HTTP-200 ok:false response for the %s toggle", async (_kind, action) => {
    setCsrfToken("csrf");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      ok: false,
      error: "Emby rejected the update",
    }), { status: 200 })));

    await expect(action({
      server_id: "server-1",
      user_id: "user-1",
      name: "Alice",
      enable_remote_access: false,
      enable_downloading: false,
    } as never)).rejects.toThrow("Emby rejected the update");
  });
});
