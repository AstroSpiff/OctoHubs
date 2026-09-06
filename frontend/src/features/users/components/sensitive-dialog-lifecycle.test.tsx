// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountEditorDialog } from "@/features/account-management/components/account-editor-dialog";
import { CreateUserDialog } from "@/features/users/components/create-user-dialog";
import { PasswordDialog } from "@/features/users/components/password-dialog";

const apiMocks = vi.hoisted(() => ({
  getPasswordInfo: vi.fn(),
  getSettingsPresets: vi.fn().mockResolvedValue({ presets: [] }),
}));

vi.mock("@/features/users/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/users/api")>()),
  getPasswordInfo: apiMocks.getPasswordInfo,
}));

vi.mock("@/features/user-settings/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/user-settings/api")>()),
  getSettingsPresets: apiMocks.getSettingsPresets,
}));

function setInputValue(input: HTMLInputElement, value: string) {
  act(() => {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

describe("secret-bearing dialog lifecycle", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    apiMocks.getPasswordInfo.mockReset();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    client.clear();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("clears account passwords before the same dialog is reopened", async () => {
    const render = (open: boolean) => root.render(
      <MemoryRouter>
        <AccountEditorDialog
          busy={false}
          onClose={vi.fn()}
          onCreate={vi.fn()}
          onUpdate={vi.fn()}
          open={open}
        />
      </MemoryRouter>,
    );
    await act(async () => render(true));
    const password = container.querySelector<HTMLInputElement>("input[type='password']");
    expect(password).not.toBeNull();
    setInputValue(password!, "transient-account-secret");

    await act(async () => render(false));
    await act(async () => render(true));
    expect(container.querySelector<HTMLInputElement>("input[type='password']")?.value).toBe("");
    expect(container.innerHTML).not.toContain("transient-account-secret");
  });

  it("clears an Emby create password before reopening", async () => {
    const render = (open: boolean) => root.render(
      <QueryClientProvider client={client}>
        <CreateUserDialog
          open={open}
          servers={[{ id: "server-1", name: "Server" }]}
          creating={false}
          onClose={vi.fn()}
          onCreate={vi.fn()}
        />
      </QueryClientProvider>,
    );
    await act(async () => render(true));
    const password = container.querySelector<HTMLInputElement>("input[type='password']");
    expect(password).not.toBeNull();
    setInputValue(password!, "transient-emby-secret");

    await act(async () => render(false));
    await act(async () => render(true));
    expect(container.querySelector<HTMLInputElement>("input[type='password']")?.value).toBe("");
    expect(container.innerHTML).not.toContain("transient-emby-secret");
  });

  it("does not expose the previous target password while opening another target", async () => {
    apiMocks.getPasswordInfo
      .mockResolvedValueOnce({ saved: true, password: "first-target-secret", updated_at: null })
      .mockResolvedValueOnce({ saved: false, password: "", updated_at: null });
    const render = (userId: string | null) => root.render(
      <PasswordDialog
        target={userId ? {
          scope: "user",
          serverId: "server-1",
          userId,
          name: userId,
        } : null}
        saving={false}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    await act(async () => render("user-1"));
    await vi.waitFor(() => {
      expect(container.querySelector<HTMLInputElement>("input[type='password']")?.value)
        .toBe("first-target-secret");
    });

    await act(async () => render(null));
    await act(async () => render("user-2"));
    await vi.waitFor(() => {
      expect(container.querySelector<HTMLInputElement>("input[type='password']")?.value)
        .toBe("");
    });
    expect(container.innerHTML).not.toContain("first-target-secret");
  });
});
