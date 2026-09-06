import type { Session } from "@/lib/session";
import { ApiError } from "@/lib/http";

type WorkspaceAccessState = "loading" | "error" | "viewer" | "editor";

function workspaceAccessState(session: {
  data?: Session;
  isPending: boolean;
  isError: boolean;
  error?: unknown;
}): WorkspaceAccessState {
  if (
    session.isError &&
    session.error instanceof ApiError &&
    (session.error.status === 401 || session.error.status === 403)
  ) {
    return "error";
  }
  // React Query retains the last authenticated value during a failed refetch.
  // Keep it only for transient failures; an authoritative auth response revokes it.
  if (session.data) {
    return session.data.user.role?.trim().toLowerCase() === "viewer"
      ? "viewer"
      : "editor";
  }
  return session.isPending ? "loading" : "error";
}

function isAuthenticatedAccessState(accessState: WorkspaceAccessState) {
  return accessState === "viewer" || accessState === "editor";
}

export {
  isAuthenticatedAccessState,
  workspaceAccessState,
  type WorkspaceAccessState,
};
