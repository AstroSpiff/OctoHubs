// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TorrentClientsSettings } from "@/features/configuration/components/torrent-clients-settings";
import type { TorrentClientInput } from "@/features/configuration/types";

describe("TorrentClientsSettings", () => {
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

  it("uses the generic Client Torrent title for the configuration section", () => {
    act(() => root.render(<TorrentClientsSettings value={[]} snapshot={[]} onChange={vi.fn()} />));

    expect(container.querySelector("h3")?.textContent).toBe("Client Torrent");
  });

  it("moves the default to another enabled client when the current default is disabled", () => {
    const onChange = vi.fn();
    const value: TorrentClientInput[] = [
      { id: "qb", name: "qBittorrent", kind: "qbittorrent", url: "http://qb", username: "admin", enabled: true, is_default: true },
      { id: "deluge", name: "Deluge", kind: "deluge", url: "http://deluge", username: "", enabled: true, is_default: false },
    ];
    act(() => root.render(<TorrentClientsSettings value={value} snapshot={[]} onChange={onChange} />));

    const enabled = container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    act(() => enabled[0].click());

    expect(onChange).toHaveBeenCalledWith([
      { ...value[0], enabled: false, is_default: false },
      { ...value[1], is_default: true },
    ]);
  });

  it("creates a unique additional profile without introducing a second default", () => {
    const onChange = vi.fn();
    const value: TorrentClientInput[] = [
      { id: "deluge", name: "Deluge", kind: "deluge", url: "", username: "", enabled: true, is_default: true },
    ];
    act(() => root.render(<TorrentClientsSettings value={value} snapshot={[]} onChange={onChange} />));

    const add = [...container.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.includes("Deluge"));
    act(() => add?.click());

    const next = onChange.mock.calls[0][0] as TorrentClientInput[];
    expect(next).toHaveLength(2);
    expect(next[1].name).toBe("Deluge 2");
    expect(next[1].enabled).toBe(false);
    expect(next.filter((client) => client.is_default)).toHaveLength(1);
  });
});
