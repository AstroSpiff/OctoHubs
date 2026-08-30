import { useCallback } from "react";
import { useBeforeUnload } from "react-router-dom";

function useBeforeUnloadWarning(enabled: boolean) {
  const warnBeforeUnload = useCallback((event: BeforeUnloadEvent) => {
    if (!enabled) return;
    event.preventDefault();
    event.returnValue = "";
  }, [enabled]);

  useBeforeUnload(warnBeforeUnload);
}

export { useBeforeUnloadWarning };
