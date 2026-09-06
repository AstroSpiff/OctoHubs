// @vitest-environment jsdom

import { MemoryRouter } from "react-router-dom";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountEditorDialog } from "@/features/account-management/components/account-editor-dialog";
import type { OctoHubsAccount } from "@/features/account-management/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const account: OctoHubsAccount = {
  id: 7,
  username: "operator",
  email: "old@example.test",
  role: "user",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  last_login: null,
};

describe("AccountEditorDialog", () => {
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
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("requires confirmation before discarding an edited account", async () => {
    const onClose = vi.fn();
    await act(async () => {
      root.render(
        <MemoryRouter>
          <AccountEditorDialog
            account={account}
            busy={false}
            onClose={onClose}
            onCreate={vi.fn()}
            onUpdate={vi.fn()}
            open
          />
        </MemoryRouter>,
      );
    });

    const role = container.querySelector<HTMLSelectElement>("select");
    expect(role).not.toBeNull();
    act(() => {
      if (!role) return;
      role.value = "admin";
      role.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const cancel = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Annulla",
    );
    act(() => cancel?.click());

    expect(onClose).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Modifiche non salvate");

    const discard = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Abbandona modifiche",
    );
    await act(async () => discard?.click());
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
