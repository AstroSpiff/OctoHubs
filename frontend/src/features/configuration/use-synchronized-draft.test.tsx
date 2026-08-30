// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useSynchronizedDraft } from "@/lib/use-synchronized-draft";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

type DraftValue = { interval: number };

let latestDraft: ReturnType<typeof useSynchronizedDraft<DraftValue, DraftValue>> | undefined;

function DraftHarness({ source }: { source: DraftValue }) {
  latestDraft = useSynchronizedDraft(source, (value) => ({ ...value }));
  return null;
}

describe("useSynchronizedDraft", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latestDraft = undefined;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("accepts a saved snapshot when the draft has not changed", () => {
    act(() => {
      root.render(<DraftHarness source={{ interval: 5 }} />);
    });
    const submitted = { interval: 10 };

    act(() => {
      latestDraft?.setDraft(() => submitted);
      latestDraft?.accept({ interval: 10 }, submitted);
    });

    expect(latestDraft?.draft).toEqual({ interval: 10 });
    expect(latestDraft?.dirty).toBe(false);
  });

  it("keeps a newer draft when a previous save response arrives", () => {
    act(() => {
      root.render(<DraftHarness source={{ interval: 5 }} />);
    });
    const submitted = { interval: 10 };

    act(() => {
      latestDraft?.setDraft(() => submitted);
      latestDraft?.setDraft(() => ({ interval: 15 }));
      latestDraft?.accept({ interval: 10 }, submitted);
    });

    expect(latestDraft?.draft).toEqual({ interval: 15 });
    expect(latestDraft?.dirty).toBe(true);
  });

  it("does not overwrite a local draft when its query refreshes", () => {
    act(() => {
      root.render(<DraftHarness source={{ interval: 5 }} />);
    });
    act(() => {
      latestDraft?.setDraft(() => ({ interval: 10 }));
    });
    act(() => {
      root.render(<DraftHarness source={{ interval: 7 }} />);
    });

    expect(latestDraft?.draft).toEqual({ interval: 10 });
    expect(latestDraft?.dirty).toBe(true);
  });
});
