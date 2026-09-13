// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GroupSyncSettingsDialog } from "@/features/users/components/group-sync-settings-dialog";
import type { EmbyUserGroup } from "@/features/users/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const group: EmbyUserGroup = {
  id: "family",
  name: "Famiglia",
  is_linked: true,
  users: [{
    server_id: "green",
    server_name: "Green",
    server_alias: "Casa",
    user_id: "leader-1",
    name: "Roy",
    is_disabled: false,
    is_user_disabled: false,
    is_remote_disabled: false,
    enable_remote_access: true,
    is_admin: false,
    is_leader: true,
  }],
  auto_sync: true,
  sync_type: "merge",
  sync_playstate: true,
};

describe("GroupSyncSettingsDialog", () => {
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

  it("does not discard unsaved group settings when the dashboard refreshes", () => {
    const render = (nextGroup: EmbyUserGroup) => {
      root.render(
        <GroupSyncSettingsDialog
          group={nextGroup}
          saving={false}
          onClose={() => undefined}
          onSave={() => undefined}
        />,
      );
    };

    act(() => render(group));
    const direction = container.querySelector("select") as HTMLSelectElement;
    act(() => {
      direction.value = "one_way";
      direction.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(direction.value).toBe("one_way");

    act(() => render({ ...group, last_sync_message: "Aggiornamento dal server" }));
    expect((container.querySelector("select") as HTMLSelectElement).value).toBe("one_way");
  });

  it("keeps manual synchronization settings editable while automation is disabled", () => {
    const onSave = vi.fn();
    act(() => {
      root.render(
        <GroupSyncSettingsDialog
          group={{ ...group, auto_sync: false, sync_type: "one_way" }}
          saving={false}
          onClose={() => undefined}
          onSave={onSave}
        />,
      );
    });

    const direction = container.querySelector("select") as HTMLSelectElement;
    const fieldsets = container.querySelectorAll("fieldset");
    expect(direction.disabled).toBe(false);
    expect((fieldsets[0] as HTMLFieldSetElement).disabled).toBe(false);
    expect((fieldsets[1] as HTMLFieldSetElement).disabled).toBe(false);
    expect((fieldsets[2] as HTMLFieldSetElement).disabled).toBe(true);
    expect(container.textContent).toContain("Roy");
    expect(container.textContent).toContain("Casa");
    expect(container.textContent).toContain("Sincronizza ora");

    act(() => container.querySelector("form")?.requestSubmit());
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      auto_sync: false,
      sync_type: "one_way",
      sync_playstate: true,
    }));
  });
});
