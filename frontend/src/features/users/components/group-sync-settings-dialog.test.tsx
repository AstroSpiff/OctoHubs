// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { GroupSyncSettingsDialog } from "@/features/users/components/group-sync-settings-dialog";
import type { EmbyUserGroup } from "@/features/users/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const group: EmbyUserGroup = {
  id: "family",
  name: "Famiglia",
  is_linked: true,
  users: [],
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
});
