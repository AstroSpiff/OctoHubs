// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GroupSyncControls } from "@/features/users/components/group-sync-controls";
import type { EmbyUserGroup } from "@/features/users/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function deferredPromise() {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
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

describe("GroupSyncControls", () => {
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

  it("keeps an inline change while a stale group refresh arrives during its save", async () => {
    const deferred = deferredPromise();
    const onSave = vi.fn(() => deferred.promise);

    act(() => {
      root.render(<GroupSyncControls group={group} saving={false} syncing={false} onSave={onSave} onSync={() => undefined} />);
    });
    const direction = container.querySelector("select") as HTMLSelectElement;

    act(() => {
      direction.value = "one_way";
      direction.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ sync_type: "one_way" }));
    expect(direction.value).toBe("one_way");
    expect(direction.disabled).toBe(true);

    act(() => {
      root.render(<GroupSyncControls group={{ ...group }} saving={false} syncing={false} onSave={onSave} onSync={() => undefined} />);
    });
    expect((container.querySelector("select") as HTMLSelectElement).value).toBe("one_way");

    await act(async () => {
      deferred.resolve();
      await deferred.promise;
    });
    act(() => {
      root.render(<GroupSyncControls group={{ ...group, sync_type: "one_way" }} saving={false} syncing={false} onSave={onSave} onSync={() => undefined} />);
    });
    expect((container.querySelector("select") as HTMLSelectElement).value).toBe("one_way");
  });

  it("keeps the last outcome visible when automatic synchronization is disabled", () => {
    act(() => {
      root.render(
        <GroupSyncControls
          group={{
            ...group,
            auto_sync: false,
            last_sync_status: "skipped",
            last_sync_message: "Leader non valido: trovati 0 leader",
          }}
          saving={false}
          syncing={false}
          onSave={() => Promise.resolve()}
          onSync={() => undefined}
        />,
      );
    });

    expect(container.textContent).toContain("Sincronizzazione da verificare");
    expect(container.textContent).toContain("Leader non valido: trovati 0 leader");
  });

  it("restores the previous value and reports a rejected autosave", async () => {
    const onSave = vi.fn(() => Promise.reject(new Error("backend offline")));
    act(() => {
      root.render(<GroupSyncControls group={group} saving={false} syncing={false} onSave={onSave} onSync={() => undefined} />);
    });
    const direction = container.querySelector("select") as HTMLSelectElement;

    await act(async () => {
      direction.value = "one_way";
      direction.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
    });

    expect(direction.value).toBe("merge");
    expect(container.textContent).toContain("Salvataggio non riuscito: backend offline");
  });
});
