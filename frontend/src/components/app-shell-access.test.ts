import { describe, expect, it } from "vitest";

import {
  isAuthenticatedAccessState,
  workspaceContentOwnerKey,
  workspaceAccessState,
} from "@/components/app-shell-access";
import { ApiError } from "@/lib/http";
import type { Session } from "@/lib/session";
import type { UiRole } from "@/lib/ui-api-contracts";

const session = (role: UiRole): Session => ({
  user: { id: 1, username: role, email: `${role}@example.test`, role },
  csrf_token: "csrf",
  preferences: {
    primary_navigation: "sidebar",
    secondary_navigation: "sidebar",
  },
});

describe("AppShell authenticated access", () => {
  it("keeps personal preferences available to viewers and editors", () => {
    expect(isAuthenticatedAccessState("viewer")).toBe(true);
    expect(isAuthenticatedAccessState("editor")).toBe(true);
    expect(isAuthenticatedAccessState("loading")).toBe(false);
    expect(isAuthenticatedAccessState("error")).toBe(false);
  });

  it("keeps the cached role during a failed background refetch", () => {
    expect(workspaceAccessState({ data: session("admin"), isPending: false, isError: true })).toBe("editor");
    expect(workspaceAccessState({ data: session("viewer"), isPending: false, isError: true })).toBe("viewer");
  });

  it("revokes a cached editor capability on authoritative auth failure", () => {
    expect(workspaceAccessState({
      data: session("admin"),
      isPending: false,
      isError: true,
      error: new ApiError("Forbidden", 403),
    })).toBe("error");
    expect(workspaceAccessState({
      data: session("admin"),
      isPending: false,
      isError: true,
      error: new Error("temporary network error"),
    })).toBe("editor");
  });

  it("fails closed when no authenticated session has ever been loaded", () => {
    expect(workspaceAccessState({ isPending: true, isError: false })).toBe("loading");
    expect(workspaceAccessState({ isPending: false, isError: true })).toBe("error");
  });

  it("changes the routed subtree key when same-role session ownership changes", () => {
    const first = session("admin").user;
    const second = { ...first, id: 2, username: "second-admin" };

    expect(workspaceContentOwnerKey("editor", first))
      .not.toBe(workspaceContentOwnerKey("editor", second));
    expect(workspaceContentOwnerKey("loading", first)).toBe("loading");
    expect(workspaceContentOwnerKey("error", first)).toBe("error");
  });
});
