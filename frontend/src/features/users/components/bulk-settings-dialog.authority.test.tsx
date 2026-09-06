// @vitest-environment jsdom

import { act } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSettingsInfo, getSettingsSchema } from "@/features/user-settings/api";
import { BulkSettingsDialog } from "@/features/users/components/bulk-settings-dialog";
import type { EmbyUser } from "@/features/users/types";

vi.mock("@/features/user-settings/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/user-settings/api")>()),
  getSettingsInfo: vi.fn(),
  getSettingsSchema: vi.fn(),
}));
vi.mock("@/features/user-settings/components/settings-preset-controls", () => ({
  SettingsPresetControls: () => null,
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const schema = {
  schema_version: 1,
  categories: [{
    id: "general",
    label: "Generali",
    policy: [{ key: "marker", label: "Valore target", type: "text" }],
  }],
};

function user(userId: string): EmbyUser {
  return {
    server_id: "green",
    server_name: "Green",
    user_id: userId,
    name: userId,
    is_disabled: false,
    is_user_disabled: false,
    is_remote_disabled: false,
    enable_remote_access: true,
    is_admin: false,
    is_leader: false,
  };
}

describe("BulkSettingsDialog authoritative targets", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    vi.mocked(getSettingsSchema).mockResolvedValue(schema);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("cannot apply A's draft during the pre-effect transition to B", async () => {
    vi.mocked(getSettingsInfo)
      .mockResolvedValueOnce({ ok: true, saved: true, settings: {}, library_items: [], feature_items: [] })
      .mockReturnValueOnce(new Promise(() => undefined));
    const onApply = vi.fn();
    await act(async () => root.render(dialog([user("A")], onApply)));
    await vi.waitFor(() => expect(container.querySelector(".bulk-settings-field-toggle input")).not.toBeNull());
    act(() => container.querySelector<HTMLInputElement>(".bulk-settings-field-toggle input")?.click());

    globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    flushSync(() => root.render(dialog([user("B")], onApply)));
    const submit = container.querySelector<HTMLButtonElement>("button[type='submit']");
    expect(submit?.disabled).toBe(true);
    container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(onApply).not.toHaveBeenCalled();
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    await act(async () => undefined);
  });
});

function dialog(users: EmbyUser[], onApply: ReturnType<typeof vi.fn>) {
  return (
    <BulkSettingsDialog
      users={users}
      saving={false}
      onClose={() => undefined}
      onApply={onApply}
    />
  );
}
