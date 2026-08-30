// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDirtyChange } from "@/lib/use-dirty-change";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function DirtyState({
  active,
  dirty,
  onDirtyChange,
}: {
  active: boolean;
  dirty: boolean;
  onDirtyChange: (dirty: boolean) => void;
}) {
  useDirtyChange(active, dirty, onDirtyChange);
  return null;
}

describe("useDirtyChange", () => {
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

  it("reports only an active dirty draft and clears it on unmount", () => {
    const onDirtyChange = vi.fn();

    act(() => {
      root.render(
        <DirtyState active={false} dirty onDirtyChange={onDirtyChange} />,
      );
    });
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);

    act(() => {
      root.render(
        <DirtyState active dirty onDirtyChange={onDirtyChange} />,
      );
    });
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);

    act(() => root.unmount());
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
  });
});
