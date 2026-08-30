import { useEffect } from "react";

type DirtyChangeHandler = (dirty: boolean) => void;

function useDirtyChange(
  active: boolean,
  dirty: boolean,
  onDirtyChange?: DirtyChangeHandler,
) {
  useEffect(() => {
    onDirtyChange?.(active && dirty);
  }, [active, dirty, onDirtyChange]);

  useEffect(
    () => () => {
      onDirtyChange?.(false);
    },
    [onDirtyChange],
  );
}

export { useDirtyChange };
export type { DirtyChangeHandler };
