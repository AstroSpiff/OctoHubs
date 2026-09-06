import { afterEach, describe, expect, it, vi } from "vitest";

import { cloneUsers } from "@/features/users/api";
import type { BulkCloneInput, EmbyUser } from "@/features/users/types";
import { SessionOwnerChangedError, setCsrfToken } from "@/lib/http";

const source: EmbyUser = {
  server_id: "source",
  server_name: "Source",
  user_id: "user-1",
  name: "Roy",
  is_disabled: false,
  is_user_disabled: false,
  is_remote_disabled: false,
  enable_remote_access: true,
  is_admin: false,
  is_leader: false,
};

describe("bulk clone owner boundary", () => {
  afterEach(() => {
    setCsrfToken("");
    vi.unstubAllGlobals();
  });

  it("does not start the next clone after the account changes", async () => {
    let resolveFirst: ((response: Response) => void) | undefined;
    const firstResponse = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const fetchMock = vi.fn().mockReturnValue(firstResponse);
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("csrf-a", 1);
    const input: BulkCloneInput = {
      sources: [{ user: source, newUsername: "Roy", linkGroup: false }],
      targetServerIds: ["target-a", "target-b"],
      syncConfig: true,
      syncPlaystate: true,
      syncResume: false,
      syncLibraryAccess: true,
      syncFavorites: true,
      syncPlaylists: true,
      configCategories: [],
    };

    const operation = cloneUsers(input);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    setCsrfToken("csrf-b", 2);
    resolveFirst?.(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await expect(operation).rejects.toBeInstanceOf(SessionOwnerChangedError);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
