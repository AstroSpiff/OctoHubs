// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getOperations } from "@/features/operations/api";
import { useCollectionOperationWatch } from "@/features/collections/use-collection-operation-watch";

vi.mock("@/features/operations/api", () => ({ getOperations: vi.fn() }));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let watch: ReturnType<typeof useCollectionOperationWatch> | undefined;

function Harness({ onCompleted }: { onCompleted: () => void }) {
  watch = useCollectionOperationWatch(onCompleted);
  return null;
}

describe("useCollectionOperationWatch", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    client.clear();
    container.remove();
    watch = undefined;
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("keeps a new operation tracked while its first query is still pending", async () => {
    vi.mocked(getOperations).mockReturnValue(new Promise(() => undefined));
    const onCompleted = vi.fn();
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <Harness onCompleted={onCompleted} />
        </QueryClientProvider>,
      );
    });

    act(() => watch?.track("operation-a", { type: "collection", collectionId: "collection-a" }));
    await act(async () => Promise.resolve());

    expect(watch?.isSyncingCollection("collection-a")).toBe(true);
    expect(onCompleted).not.toHaveBeenCalled();
  });
});
