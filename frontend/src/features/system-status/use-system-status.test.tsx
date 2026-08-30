// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSystemStatus } from "@/features/system-status/api";
import type { SystemSection, SystemStatus } from "@/features/system-status/types";
import { useSystemStatus } from "@/features/system-status/use-system-status";

vi.mock("@/features/system-status/api", () => ({
  getSystemStatus: vi.fn(),
}));

vi.mock("@/lib/use-application-event", () => ({
  useApplicationEventRefresh: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function section(summary: string): SystemSection {
  return {
    id: "emby",
    title: "Server Emby",
    severity: "ok",
    status_code: "ok",
    status_label: "OK",
    href: "/emby#actions",
    refresh_interval_seconds: 30,
    items: [
      {
        id: "server",
        label: "Emby",
        severity: "ok",
        status_code: "connected",
        status_label: "Connesso",
        summary,
        detail: "",
        href: "",
        metrics: [],
      },
    ],
  };
}

function snapshot(currentSection: SystemSection): SystemStatus {
  return {
    ok: true,
    generated_at: "2026-08-14 20:00:00 UTC",
    sections: [currentSection],
    section: currentSection,
  };
}

let latestStatus: ReturnType<typeof useSystemStatus> | undefined;

function StatusHarness() {
  latestStatus = useSystemStatus();
  return null;
}

describe("useSystemStatus", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latestStatus = undefined;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("keeps a newer full snapshot when an older section refresh resolves later", async () => {
    const staleSection = deferred<SystemStatus>();
    const fullSnapshot = deferred<SystemStatus>();
    const initial = snapshot(section("Stato iniziale"));
    vi.mocked(getSystemStatus)
      .mockResolvedValueOnce(initial)
      .mockReturnValueOnce(staleSection.promise)
      .mockReturnValueOnce(fullSnapshot.promise);

    await act(async () => {
      root.render(<StatusHarness />);
      await Promise.resolve();
    });

    expect(latestStatus?.sections[0].items[0].summary).toBe("Stato iniziale");

    act(() => {
      void latestStatus?.refreshSection("emby");
      void latestStatus?.refreshAll();
    });

    await act(async () => {
      fullSnapshot.resolve(snapshot(section("Snapshot completo aggiornato")));
      await fullSnapshot.promise;
    });
    await act(async () => {
      staleSection.resolve(snapshot(section("Risposta area superata")));
      await staleSection.promise;
    });

    expect(latestStatus?.sections[0].items[0].summary).toBe(
      "Snapshot completo aggiornato",
    );
  });
});
