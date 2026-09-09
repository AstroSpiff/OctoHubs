// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { getPasswordInfo } from "@/features/users/api";
import { PasswordDialog } from "@/features/users/components/password-dialog";

vi.mock("@/components/ui/use-confirmation-dialog", () => ({
  useConfirmationDialog: vi.fn(),
}));
vi.mock("@/features/users/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/users/api")>()),
  getPasswordInfo: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

const target = {
  scope: "user" as const,
  serverId: "green",
  userId: "user-1",
  name: "Roy",
  hasEmbyPassword: true,
};

describe("PasswordDialog authoritative snapshot", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let onSave: Mock<(password: string) => void>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    onSave = vi.fn();
    vi.mocked(useConfirmationDialog).mockReturnValue({
      confirm: vi.fn().mockResolvedValue(true),
      dialog: <></>,
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("keeps reset fenced while the password snapshot is pending", async () => {
    vi.mocked(getPasswordInfo).mockReturnValue(new Promise(() => undefined));
    await renderDialog(root, onSave);

    expect(container.textContent).toContain("Verifica password salvata");
    expect(resetButton(container).disabled).toBe(true);
    resetButton(container).click();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("keeps reset fenced and never claims success-empty after rejection", async () => {
    vi.mocked(getPasswordInfo).mockRejectedValue(new Error("lettura password fallita"));
    await renderDialog(root, onSave);
    await vi.waitFor(() => expect(container.textContent).toContain("lettura password fallita"));

    expect(container.textContent).toContain("Stato password non disponibile");
    expect(container.textContent).not.toContain("Password non salvata");
    expect(resetButton(container).disabled).toBe(true);
    resetButton(container).click();
    expect(onSave).not.toHaveBeenCalled();
  });

  it.each([
    ["success-empty", { ok: true, saved: false, password: "", updated_at: null }],
    ["success-value", { ok: true, saved: true, password: "saved-secret", updated_at: null }],
  ])("allows the legacy reset workflow only after %s", async (_state, result) => {
    vi.mocked(getPasswordInfo).mockResolvedValue(result);
    await renderDialog(root, onSave);
    await vi.waitFor(() => expect(resetButton(container).disabled).toBe(false));

    await act(async () => resetButton(container).click());
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith(""));
  });

  it("hides a successful A snapshot when B fails", async () => {
    const loadB = deferred<Awaited<ReturnType<typeof getPasswordInfo>>>();
    vi.mocked(getPasswordInfo)
      .mockResolvedValueOnce({ ok: true, saved: true, password: "owner-a-secret", updated_at: null })
      .mockReturnValueOnce(loadB.promise);
    await renderDialog(root, onSave);
    await vi.waitFor(() => expect(container.querySelector<HTMLInputElement>("input[type='password']")?.value).toBe("owner-a-secret"));

    await act(async () => root.render(dialog(onSave, { ...target, userId: "user-2", name: "B" })));
    expect(container.querySelector<HTMLInputElement>("input[type='password']")?.value).toBe("");
    expect(resetButton(container).disabled).toBe(true);

    await act(async () => loadB.reject(new Error("B unavailable")));
    await vi.waitFor(() => expect(container.textContent).toContain("B unavailable"));
    expect(container.innerHTML).not.toContain("owner-a-secret");
    expect(resetButton(container).disabled).toBe(true);
  });

  it("does not apply a confirmed reset after the authoritative target changes", async () => {
    const confirmation = deferred<boolean>();
    vi.mocked(useConfirmationDialog).mockReturnValue({
      confirm: vi.fn(() => confirmation.promise),
      dialog: <></>,
    });
    vi.mocked(getPasswordInfo)
      .mockResolvedValueOnce({ ok: true, saved: true, password: "owner-a-secret", updated_at: null })
      .mockReturnValueOnce(new Promise(() => undefined));
    await renderDialog(root, onSave);
    await vi.waitFor(() => expect(resetButton(container).disabled).toBe(false));

    act(() => resetButton(container).click());
    await act(async () => root.render(dialog(onSave, { ...target, userId: "user-2", name: "B" })));
    await act(async () => confirmation.resolve(true));

    expect(onSave).not.toHaveBeenCalled();
  });
});

async function renderDialog(
  root: ReturnType<typeof createRoot>,
  onSave: (password: string) => void,
) {
  await act(async () => root.render(dialog(onSave, target)));
}

function dialog(
  onSave: (password: string) => void,
  nextTarget: typeof target,
) {
  return (
    <PasswordDialog
      target={nextTarget}
      saving={false}
      onClose={() => undefined}
      onSave={onSave}
    />
  );
}

function resetButton(container: HTMLElement) {
  const button = container.querySelector<HTMLButtonElement>(".users-password-reset");
  if (!button) throw new Error("missing password reset button");
  return button;
}
