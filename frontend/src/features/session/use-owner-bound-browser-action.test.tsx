// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import {
  StaleBrowserActionError,
  useOwnerBoundBrowserAction,
  type OwnerBoundBrowserAction,
} from "@/features/session/use-owner-bound-browser-action";
import { setCsrfToken } from "@/lib/http";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let beginAction: (() => OwnerBoundBrowserAction) | undefined;

function Harness() {
  beginAction = useOwnerBoundBrowserAction();
  return null;
}

describe("owner-bound browser action lifecycle", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    setCsrfToken("owner-a", 1);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    beginAction = undefined;
    setCsrfToken("");
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("aborts and invalidates a lease when its account owner changes", async () => {
    await act(async () => {
      root.render(
        <WorkspaceCapabilitiesProvider accountId={1} canMutate>
          <Harness />
        </WorkspaceCapabilitiesProvider>,
      );
    });
    const action = beginAction!();
    expect(action.signal.aborted).toBe(false);
    action.assertCurrent();

    setCsrfToken("owner-b", 2);
    await act(async () => {
      root.render(
        <WorkspaceCapabilitiesProvider accountId={2} canMutate>
          <Harness />
        </WorkspaceCapabilitiesProvider>,
      );
    });

    expect(action.signal.aborted).toBe(true);
    expect(() => action.assertCurrent()).toThrow(StaleBrowserActionError);
  });

  it("aborts a lease when its component unmounts", async () => {
    await act(async () => {
      root.render(
        <WorkspaceCapabilitiesProvider accountId={1} canMutate>
          <Harness />
        </WorkspaceCapabilitiesProvider>,
      );
    });
    const action = beginAction!();

    await act(async () => root.render(<></>));

    expect(action.signal.aborted).toBe(true);
    expect(() => action.assertCurrent()).toThrow(StaleBrowserActionError);
  });
});
