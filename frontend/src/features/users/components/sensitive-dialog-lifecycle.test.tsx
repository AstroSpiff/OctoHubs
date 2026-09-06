// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountEditorDialog } from "@/features/account-management/components/account-editor-dialog";
import { SettingsEditorDialog } from "@/features/user-settings/components/settings-editor-dialog";
import { CreateUserDialog } from "@/features/users/components/create-user-dialog";
import { PasswordDialog } from "@/features/users/components/password-dialog";

const apiMocks = vi.hoisted(() => ({
  getPasswordInfo: vi.fn(),
  getSettingsInfo: vi.fn(),
  getSettingsPresets: vi.fn().mockResolvedValue({ presets: [] }),
  getSettingsSchema: vi.fn(),
  saveSettings: vi.fn(),
}));

vi.mock("@/features/users/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/users/api")>()),
  getPasswordInfo: apiMocks.getPasswordInfo,
}));

vi.mock("@/features/user-settings/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/user-settings/api")>()),
  getSettingsInfo: apiMocks.getSettingsInfo,
  getSettingsPresets: apiMocks.getSettingsPresets,
  getSettingsSchema: apiMocks.getSettingsSchema,
  saveSettings: apiMocks.saveSettings,
}));

vi.mock("@/lib/use-application-event", () => ({
  useApplicationEvent: vi.fn(),
  useApplicationEventRefresh: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

const settingsSchema = {
  schema_version: 1,
  categories: [{
    id: "general",
    label: "Generali",
    policy: [{ key: "marker", label: "Valore target", type: "text" }],
  }],
};

function settingsInfo(marker: string) {
  return {
    ok: true,
    saved: true,
    settings: { policy: { marker } },
    library_items: [],
    feature_items: [],
  };
}

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
    apiMocks.getSettingsInfo.mockReset();
    apiMocks.getSettingsSchema.mockReset();
    apiMocks.getSettingsSchema.mockResolvedValue(settingsSchema);
    apiMocks.saveSettings.mockReset();
    apiMocks.saveSettings.mockResolvedValue({ ok: true });
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

  it("hides settings from target A while target B is loading", async () => {
    const targetB = deferred<ReturnType<typeof settingsInfo>>();
    apiMocks.getSettingsInfo
      .mockResolvedValueOnce(settingsInfo("target-a-value"))
      .mockReturnValueOnce(targetB.promise);
    const render = (userId: string) => root.render(
      <QueryClientProvider client={client}>
        <SettingsEditorDialog
          target={{ scope: "user", serverId: "server-1", userId, name: userId }}
          onClose={vi.fn()}
          onSaved={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await act(async () => render("user-a"));
    await vi.waitFor(() => {
      expect(container.querySelector<HTMLInputElement>("input[type='text']")?.value)
        .toBe("target-a-value");
    });

    await act(async () => render("user-b"));
    expect(container.textContent).toContain("Caricamento impostazioni...");
    expect(container.innerHTML).not.toContain("target-a-value");
    expect(container.querySelector(".user-settings-panel")).toBeNull();

    await act(async () => targetB.resolve(settingsInfo("target-b-value")));
    await vi.waitFor(() => {
      expect(container.querySelector<HTMLInputElement>("input[type='text']")?.value)
        .toBe("target-b-value");
    });
  });

  it("keeps the previous target hidden when the next settings load fails", async () => {
    const targetB = deferred<ReturnType<typeof settingsInfo>>();
    apiMocks.getSettingsInfo
      .mockResolvedValueOnce(settingsInfo("private-target-a-value"))
      .mockReturnValueOnce(targetB.promise);
    const render = (userId: string) => root.render(
      <QueryClientProvider client={client}>
        <SettingsEditorDialog
          target={{ scope: "user", serverId: "server-1", userId, name: userId }}
          onClose={vi.fn()}
          onSaved={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await act(async () => render("user-a"));
    await vi.waitFor(() => expect(container.innerHTML).toContain("private-target-a-value"));
    await act(async () => render("user-b"));
    await act(async () => targetB.reject(new Error("target B unavailable")));

    await vi.waitFor(() => expect(container.textContent).toContain("target B unavailable"));
    expect(container.innerHTML).not.toContain("private-target-a-value");
    expect(container.querySelector(".user-settings-panel")).toBeNull();
  });

  it("does not let target A post-save refresh overwrite loaded target B", async () => {
    const targetARefresh = deferred<ReturnType<typeof settingsInfo>>();
    apiMocks.getSettingsInfo
      .mockResolvedValueOnce(settingsInfo("target-a-before-save"))
      .mockReturnValueOnce(targetARefresh.promise)
      .mockResolvedValueOnce(settingsInfo("target-b-current"));
    const onSaved = vi.fn();
    const render = (userId: string) => root.render(
      <QueryClientProvider client={client}>
        <SettingsEditorDialog
          target={{ scope: "user", serverId: "server-1", userId, name: userId }}
          onClose={vi.fn()}
          onSaved={onSaved}
        />
      </QueryClientProvider>,
    );

    await act(async () => render("user-a"));
    await vi.waitFor(() => expect(container.innerHTML).toContain("target-a-before-save"));
    await act(async () => {
      container.querySelector("form")?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(apiMocks.getSettingsInfo).toHaveBeenCalledTimes(2);

    await act(async () => render("user-b"));
    await vi.waitFor(() => {
      expect(container.querySelector<HTMLInputElement>("input[type='text']")?.value)
        .toBe("target-b-current");
    });
    await act(async () => targetARefresh.resolve(settingsInfo("stale-target-a-refresh")));

    expect(container.querySelector<HTMLInputElement>("input[type='text']")?.value)
      .toBe("target-b-current");
    expect(container.innerHTML).not.toContain("stale-target-a-refresh");
    expect(onSaved).toHaveBeenCalledTimes(1);
  });
});
