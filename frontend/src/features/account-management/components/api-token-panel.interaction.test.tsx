// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiTokenPanel } from "@/features/account-management/components/api-token-panel";
import type {
  ApiToken,
  CreatedApiToken,
} from "@/features/account-management/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("ApiTokenPanel token creation", () => {
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

  it("shows the one-time secret and copies it after a profile-based creation", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const onCreate = vi.fn().mockResolvedValue({
      secret: "ohs_secret_visible_once",
      message: "API token creato.",
      token: {
        id: 1,
        name: "Agente IA",
        prefix: "ohs_secret",
        scopes: ["read:status"],
        permission_profile: "read_only",
        is_active: true,
        is_expired: false,
        status: "active",
        created_at: null,
        last_used_at: null,
        revoked_at: null,
        expires_at: null,
        last_action: null,
      },
    });

    act(() => {
      root.render(
        <ApiTokenPanel
          availablePermissionProfiles={[
            { id: "read_only", scopes: ["read:status"] },
            { id: "operator", scopes: ["read:status", "run:operations"] },
          ]}
          tokens={[]}
          loading={false}
          creating={false}
          onCreate={onCreate}
          onRevoke={vi.fn().mockResolvedValue(undefined)}
          onRotate={vi.fn()}
        />,
      );
    });

    const nameInput = container.querySelector<HTMLInputElement>('input[placeholder^="IA esterna"]');
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(nameInput, "Agente IA");
      nameInput?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const operator = container.querySelector<HTMLInputElement>('input[value="operator"]');
    act(() => {
      operator?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await act(async () => {
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(onCreate).toHaveBeenCalledWith({ name: "Agente IA", permissionProfile: "operator", expiresInDays: 90 });
    expect(container.querySelector<HTMLInputElement>('[aria-label="Token appena creato"]')?.value).toBe("ohs_secret_visible_once");

    await act(async () => {
      Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.includes("Copia"))?.click();
    });
    expect(writeText).toHaveBeenCalledWith("ohs_secret_visible_once");
  });

  it("serializes token operations until the one-time secret is acknowledged", async () => {
    let resolveRotation!: (value: CreatedApiToken) => void;
    const rotation = new Promise<CreatedApiToken>((resolve) => {
      resolveRotation = resolve;
    });
    const onRotate = vi.fn(() => rotation);
    const onRevoke = vi.fn().mockResolvedValue(undefined);
    const onSecretPendingChange = vi.fn();
    const tokens = [token(1, "Token A"), token(2, "Token B")];

    act(() => {
      root.render(
        <ApiTokenPanel
          availablePermissionProfiles={[
            { id: "read_only", scopes: ["read:status"] },
          ]}
          tokens={tokens}
          loading={false}
          creating={false}
          onCreate={vi.fn()}
          onRevoke={onRevoke}
          onRotate={onRotate}
          onSecretPendingChange={onSecretPendingChange}
        />,
      );
    });

    act(() => {
      container
        .querySelector<HTMLButtonElement>('[aria-label="Ruota Token A"]')
        ?.click();
    });
    await act(async () => {
      const dialog = container.querySelector('[role="alertdialog"]');
      Array.from(dialog?.querySelectorAll("button") || [])
        .find((button) => button.textContent === "Ruota token")
        ?.click();
      await Promise.resolve();
    });

    expect(onRotate).toHaveBeenCalledTimes(1);
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Ruota Token B"]')
        ?.disabled,
    ).toBe(true);
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Revoca Token B"]')
        ?.disabled,
    ).toBe(true);

    await act(async () => {
      resolveRotation({
        token: tokens[0],
        secret: "ohs_rotated_visible_once",
        message: "Token ruotato",
      });
      await rotation;
    });
    expect(
      container.querySelector<HTMLInputElement>('[aria-label="Token appena creato"]')
        ?.value,
    ).toBe("ohs_rotated_visible_once");
    expect(onSecretPendingChange).toHaveBeenLastCalledWith(true);
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Ruota Token B"]')
        ?.disabled,
    ).toBe(true);
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Revoca Token B"]')
        ?.disabled,
    ).toBe(true);
    act(() => {
      container
        .querySelector<HTMLButtonElement>('[aria-label="Revoca Token B"]')
        ?.click();
    });
    expect(onRevoke).not.toHaveBeenCalled();

    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[aria-label="Nascondi token"]')
        ?.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alertdialog"]')).not.toBeNull();
    await act(async () => {
      const dialog = container.querySelector('[role="alertdialog"]');
      Array.from(dialog?.querySelectorAll("button") || [])
        .find((button) => button.textContent === "Nascondi token")
        ?.click();
      await Promise.resolve();
    });
    expect(onSecretPendingChange).toHaveBeenLastCalledWith(false);
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Ruota Token B"]')
        ?.disabled,
    ).toBe(false);
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Revoca Token B"]')
        ?.disabled,
    ).toBe(false);
  });
});

function token(id: number, name: string): ApiToken {
  return {
    id,
    name,
    prefix: `ohs_${id}`,
    scopes: ["read:status"],
    permission_profile: "read_only",
    is_active: true,
    is_expired: false,
    status: "active",
    created_at: null,
    last_used_at: null,
    revoked_at: null,
    expires_at: null,
    last_action: null,
  };
}
