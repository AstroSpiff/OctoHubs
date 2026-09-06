// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCollectionEnabled } from "@/features/collections/api";
import {
  collectionActionKey,
  useCollections,
} from "@/features/collections/use-collections";

vi.mock("@/features/collections/api", () => ({
  deleteCollection: vi.fn(),
  deleteCollectionImage: vi.fn(),
  getCollectionOptions: vi.fn().mockResolvedValue({ servers: [], source_types: [] }),
  getCollections: vi.fn().mockResolvedValue({ collections: [] }),
  saveCollection: vi.fn(),
  setCollectionEnabled: vi.fn(),
  syncAllCollections: vi.fn(),
  syncCollection: vi.fn(),
  uploadCollectionImage: vi.fn(),
}));

vi.mock("@/features/collections/use-collection-operation-watch", () => ({
  useCollectionOperationWatch: () => ({
    isSyncingAll: false,
    isSyncingCollection: () => false,
    track: vi.fn(),
  }),
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
  reject: (reason: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

let latest: ReturnType<typeof useCollections> | undefined;

function Harness() {
  latest = useCollections();
  return null;
}

describe("useCollections keyed actions", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <Harness />
        </QueryClientProvider>,
      );
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    client.clear();
    container.remove();
    latest = undefined;
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("keeps pending and failure state attached to each collection", async () => {
    const first = deferred<Awaited<ReturnType<typeof setCollectionEnabled>>>();
    const second = deferred<Awaited<ReturnType<typeof setCollectionEnabled>>>();
    vi.mocked(setCollectionEnabled)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    act(() => {
      latest?.toggle.mutate({ collectionId: "a", enabled: false });
      latest?.toggle.mutate({ collectionId: "b", enabled: false });
    });

    expect(latest?.toggleOperations.pendingKeys).toEqual(
      new Set([collectionActionKey("a"), collectionActionKey("b")]),
    );

    await act(async () => {
      second.resolve({ success: true });
      await second.promise;
    });
    await act(async () => {
      first.reject(new Error("A non salvata"));
      try {
        await first.promise;
      } catch {
        // The hook exposes the controlled mutation failure through keyed state.
      }
    });

    expect(latest?.toggleOperations.pendingKeys.size).toBe(0);
    expect(latest?.toggleOperations.errors).toEqual({
      [collectionActionKey("a")]: "A non salvata",
    });
  });
});
