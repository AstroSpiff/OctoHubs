import { useCallback, useEffect, useRef } from "react";

import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import {
  SessionOwnerChangedError,
  assertAuthenticatedActionOwner,
  captureAuthenticatedActionOwner,
} from "@/lib/http";

class StaleBrowserActionError extends Error {
  constructor() {
    super("L'azione non appartiene più alla sessione corrente.");
    this.name = "StaleBrowserActionError";
  }
}

type OwnerBoundBrowserAction = {
  assertCurrent: () => void;
  release: () => void;
  signal: AbortSignal;
};

function useOwnerBoundBrowserAction() {
  const { accountId } = useWorkspaceCapabilities();
  const lifecycleGeneration = useRef(0);
  const controllers = useRef(new Set<AbortController>());

  useEffect(() => {
    const activeControllers = controllers.current;
    return () => {
      lifecycleGeneration.current += 1;
      activeControllers.forEach((controller) => controller.abort());
      activeControllers.clear();
    };
  }, [accountId]);

  return useCallback((): OwnerBoundBrowserAction => {
    const controller = new AbortController();
    const owner = captureAuthenticatedActionOwner();
    const generation = lifecycleGeneration.current;
    controllers.current.add(controller);

    return {
      signal: controller.signal,
      assertCurrent() {
        if (controller.signal.aborted || generation !== lifecycleGeneration.current) {
          throw new StaleBrowserActionError();
        }
        assertAuthenticatedActionOwner(owner);
      },
      release() {
        controllers.current.delete(controller);
      },
    };
  }, []);
}

function isOwnerBoundBrowserActionCancelled(reason: unknown) {
  return reason instanceof StaleBrowserActionError
    || reason instanceof SessionOwnerChangedError
    || (reason instanceof DOMException && reason.name === "AbortError");
}

export {
  StaleBrowserActionError,
  isOwnerBoundBrowserActionCancelled,
  useOwnerBoundBrowserAction,
};
export type { OwnerBoundBrowserAction };
