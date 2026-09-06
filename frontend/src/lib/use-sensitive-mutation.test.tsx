// @vitest-environment jsdom

import { QueryClient } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSensitiveMutation } from "@/lib/use-sensitive-mutation";

let latest: ReturnType<typeof useSensitiveMutation<{ ok: true }, { password: string }, string>> | undefined;
let release: (() => void) | undefined;

function Harness() {
  latest = useSensitiveMutation({
    mutationFn: async () => {
      await new Promise<void>((resolve) => { release = resolve; });
      return { ok: true };
    },
    publicVariables: () => "redacted-operation",
  });
  return null;
}

describe("useSensitiveMutation", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latest = undefined;
    release = undefined;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<Harness />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("never publishes secret variables or results to TanStack MutationCache", async () => {
    const queryClient = new QueryClient();
    let pending!: Promise<{ ok: true }>;
    act(() => {
      pending = latest!.mutateAsync({ password: "temporary-password" });
    });

    expect(latest?.isPending).toBe(true);
    expect(latest?.variables).toBe("redacted-operation");
    expect(queryClient.getMutationCache().getAll()).toEqual([]);

    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    await act(async () => {
      release!();
      await pending;
    });

    expect(latest?.isPending).toBe(false);
    expect(latest?.variables).toBeUndefined();
    expect(latest?.data).toBeUndefined();
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
  });
});
