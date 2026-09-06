// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getUserDetails } from "@/features/users/api";
import { UserDetailsDialog } from "@/features/users/components/user-details-dialog";

vi.mock("@/features/users/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/users/api")>()),
  getUserDetails: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const user = {
  server_id: "green",
  server_name: "Green",
  user_id: "u1",
  name: "Roy",
  is_disabled: false,
  is_user_disabled: false,
  is_remote_disabled: false,
  enable_remote_access: true,
  is_admin: false,
  is_leader: false,
  has_password: true,
  password_status: "mismatch",
  last_login: "2026-09-06T10:00:00Z",
};

describe("UserDetailsDialog authoritative details", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("does not render never-values before a successful details snapshot", async () => {
    vi.mocked(getUserDetails).mockRejectedValue(new Error("profile unavailable"));
    await act(async () => root.render(<UserDetailsDialog user={user} onClose={() => undefined} />));
    await vi.waitFor(() => expect(container.textContent).toContain("profile unavailable"));

    expect(container.textContent).toContain("Riprova");
    expect(container.textContent).not.toContain("Ultima attività");
    expect(container.textContent).not.toContain("Ultimo contenuto");
    expect(container.textContent).not.toContain("Mai");
  });

  it("renders success-empty as never only after the snapshot resolves", async () => {
    vi.mocked(getUserDetails).mockResolvedValue({
      last_activity_date: null,
      date_created: null,
      last_played_date: null,
      last_played_title: null,
      has_password: false,
    });
    await act(async () => root.render(<UserDetailsDialog user={user} onClose={() => undefined} />));
    await vi.waitFor(() => expect(container.textContent).toContain("Ultimo contenuto"));

    expect(container.textContent).toContain("Mai");
    expect(container.textContent).toContain("Emby: assente");
  });
});
