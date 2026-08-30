import { useEffect, useRef } from "react";
import { useBlocker } from "react-router-dom";

import type { ConfirmationOptions } from "@/components/ui/confirmation-dialog";

const navigationWarning: ConfirmationOptions = {
  title: "Modifiche non salvate",
  description: "Lasciare questa pagina e perdere le modifiche in corso?",
  confirmLabel: "Abbandona modifiche",
  tone: "danger",
};

function isPageNavigation(currentPathname: string, nextPathname: string): boolean {
  return currentPathname !== nextPathname;
}

function useUnsavedChangesNavigationGuard(
  enabled: boolean,
  confirm: (options: ConfirmationOptions) => Promise<boolean>,
) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    enabled && isPageNavigation(currentLocation.pathname, nextLocation.pathname),
  );
  const prompting = useRef(false);

  useEffect(() => {
    if (blocker.state !== "blocked" || prompting.current) return;
    prompting.current = true;
    void confirm(navigationWarning).then((confirmed) => {
      prompting.current = false;
      if (confirmed) blocker.proceed();
      else blocker.reset();
    });
  }, [blocker, confirm]);
}

export { useUnsavedChangesNavigationGuard };
export { isPageNavigation };
