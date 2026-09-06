// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/users/api", () => ({ checkUserName: vi.fn() }));

import { checkUserName } from "@/features/users/api";
import { CloneUserDialog } from "@/features/users/components/clone-user-dialog";
import type { EmbyUser } from "@/features/users/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const user: EmbyUser = {
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

describe("CloneUserDialog lifecycle", () => {
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

  it("does not clone after a pending name preflight outlives the dialog", async () => {
    let resolveCheck: ((value: { exists: boolean }) => void) | undefined;
    vi.mocked(checkUserName).mockReturnValue(new Promise((resolve) => {
      resolveCheck = resolve;
    }));
    const onClone = vi.fn();
    await act(async () => {
      root.render(
        <CloneUserDialog
          users={[user]}
          groups={[]}
          servers={[{ id: "source", name: "Source" }, { id: "target", name: "Target" }]}
          cloning={false}
          onClose={() => undefined}
          onClone={onClone}
        />,
      );
    });

    await act(async () => {
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await vi.waitFor(() => expect(checkUserName).toHaveBeenCalledOnce());
    act(() => root.unmount());
    resolveCheck?.({ exists: false });
    await Promise.resolve();

    expect(onClone).not.toHaveBeenCalled();
  });
});
