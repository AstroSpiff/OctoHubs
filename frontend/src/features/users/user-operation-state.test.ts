import { describe, expect, it } from "vitest";

import { isUserOperationPending } from "@/features/users/user-operation-state";
import type { EmbyUser } from "@/features/users/types";

const firstUser = {
  server_id: "server-a",
  user_id: "user-a",
  name: "Anna",
} as EmbyUser;
const secondUser = {
  server_id: "server-b",
  user_id: "user-b",
  name: "Bruno",
} as EmbyUser;

describe("user operation state", () => {
  it("locks only the user targeted by a direct operation", () => {
    expect(
      isUserOperationPending(firstUser, { remote: firstUser }),
    ).toBe(true);
    expect(
      isUserOperationPending(secondUser, { remote: firstUser }),
    ).toBe(false);
  });

  it("recognizes pending password, clone, and bulk settings operations", () => {
    expect(
      isUserOperationPending(firstUser, {
        password: {
          target: {
            scope: "user",
            serverId: firstUser.server_id,
            userId: firstUser.user_id,
            name: firstUser.name,
          },
        },
      }),
    ).toBe(true);
    expect(
      isUserOperationPending(firstUser, {
        applySettings: { users: [secondUser] },
      }),
    ).toBe(false);
    expect(
      isUserOperationPending(firstUser, {
        clone: {
          sources: [{ user: firstUser, newUsername: "Anna copia", linkGroup: false }],
          targetServerIds: ["server-b"],
          syncConfig: true,
          syncPlaystate: true,
          syncResume: false,
          syncLibraryAccess: true,
          syncFavorites: true,
          syncPlaylists: true,
          configCategories: [],
        },
      }),
    ).toBe(true);
  });
});
