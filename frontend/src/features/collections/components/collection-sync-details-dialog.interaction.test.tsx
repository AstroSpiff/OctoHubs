// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCollectionSyncDetails,
  requestCollectionItemFromJellyseerr,
} from "@/features/collections/api";
import { CollectionSyncDetailsDialog } from "@/features/collections/components/collection-sync-details-dialog";


vi.mock("@/features/collections/api", () => ({
  getCollectionSyncDetails: vi.fn(),
  requestCollectionItemFromJellyseerr: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

describe("CollectionSyncDetailsDialog collection changes", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("removes the previous collection actions while the next details load", async () => {
    const unresolved = new Promise<never>(() => undefined);
    vi.mocked(getCollectionSyncDetails)
      .mockResolvedValueOnce({
        success: true,
        details: [{ server_id: "green", items: [{ title: "Old movie", tmdb_id: 42, media_type: "movie", found: false }] }],
      })
      .mockReturnValueOnce(unresolved);

    await act(async () => {
      root.render(
        <MemoryRouter><CollectionSyncDetailsDialog collection={{ id: "old", name: "Old", enabled: true }} onClose={() => undefined} /></MemoryRouter>,
      );
    });
    expect(container.textContent).toContain("Old movie");

    act(() => {
      flushSync(() => {
        root.render(
          <MemoryRouter><CollectionSyncDetailsDialog collection={{ id: "new", name: "New", enabled: true }} onClose={() => undefined} /></MemoryRouter>,
        );
      });
    });

    expect(container.textContent).toContain("Caricamento dettagli");
    expect(container.textContent).not.toContain("Old movie");
    expect(container.textContent).not.toContain("Jellyseerr");
  });

  it("shows retry without inventing success-empty when details fail", async () => {
    vi.mocked(getCollectionSyncDetails).mockRejectedValue(new Error("details unavailable"));

    await act(async () => {
      root.render(
        <MemoryRouter><CollectionSyncDetailsDialog collection={{ id: "broken", name: "Broken", enabled: true }} onClose={() => undefined} /></MemoryRouter>,
      );
    });
    await vi.waitFor(() => expect(container.textContent).toContain("details unavailable"));

    expect(container.textContent).toContain("Riprova");
    expect(container.textContent).not.toContain("Nessun dettaglio registrato");
    expect(container.textContent).not.toContain("Caricamento dettagli");
  });

  it("ignores a Jellyseerr result after switching to another collection", async () => {
    const oldRequest = deferred<{ success: boolean; message?: string }>();
    vi.mocked(getCollectionSyncDetails)
      .mockResolvedValueOnce({
        success: true,
        details: [{ server_id: "green", items: [{ title: "Old movie", tmdb_id: 42, media_type: "movie", found: false }] }],
      })
      .mockResolvedValueOnce({
        success: true,
        details: [{ server_id: "blue", items: [{ title: "New movie", tmdb_id: 84, media_type: "movie", found: false }] }],
      });
    vi.mocked(requestCollectionItemFromJellyseerr).mockReturnValue(oldRequest.promise);

    await act(async () => {
      root.render(
        <MemoryRouter><CollectionSyncDetailsDialog collection={{ id: "old", name: "Old", enabled: true }} onClose={() => undefined} /></MemoryRouter>,
      );
    });

    act(() => {
      [...container.querySelectorAll<HTMLButtonElement>("button")]
        .find((button) => button.textContent?.trim() === "Jellyseerr")
        ?.click();
    });

    expect(requestCollectionItemFromJellyseerr).toHaveBeenCalledTimes(1);
    expect(container.querySelector<HTMLButtonElement>("footer button")?.disabled).toBe(true);

    await act(async () => {
      root.render(
        <MemoryRouter><CollectionSyncDetailsDialog collection={{ id: "new", name: "New", enabled: true }} onClose={() => undefined} /></MemoryRouter>,
      );
    });
    expect(container.textContent).toContain("New movie");

    await act(async () => {
      oldRequest.resolve({ success: true, message: "Old request completed" });
      await oldRequest.promise;
    });

    expect(container.textContent).toContain("New movie");
    expect(container.textContent).not.toContain("Old request completed");
    expect(container.textContent).not.toContain("Old movie");
  });
});
