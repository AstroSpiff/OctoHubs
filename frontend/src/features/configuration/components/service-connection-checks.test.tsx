// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ServiceConnectionChecks } from "@/features/configuration/components/service-connection-checks";

describe("ServiceConnectionChecks", () => {
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

  it("shows the aggregate torrent status without a duplicate legacy qBittorrent card", () => {
    act(() => root.render(<ServiceConnectionChecks statuses={{
      qbittorrent: { ok: false, message: "Non configurato", configured: false },
      torrent_clients: { ok: true, message: "Deluge: Connessione OK", configured: true },
    }} />));

    expect(container.textContent).toContain("Client Torrent");
    expect(container.textContent).toContain("Deluge: Connessione OK");
    expect(container.textContent).not.toContain("qBittorrent");
  });
});
