import { useCallback, useEffect, useRef, useState } from "react";

import {
  ConfirmationDialog,
  type ConfirmationOptions,
} from "@/components/ui/confirmation-dialog";

function useConfirmationDialog() {
  const [options, setOptions] = useState<ConfirmationOptions | null>(null);
  const resolveRef = useRef<((confirmed: boolean) => void) | null>(null);

  const settle = useCallback((confirmed: boolean) => {
    const resolve = resolveRef.current;
    resolveRef.current = null;
    setOptions(null);
    resolve?.(confirmed);
  }, []);

  const confirm = useCallback((nextOptions: ConfirmationOptions) => {
    resolveRef.current?.(false);
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
      setOptions(nextOptions);
    });
  }, []);

  useEffect(() => () => resolveRef.current?.(false), []);

  return {
    confirm,
    dialog: (
      <ConfirmationDialog
        open={options !== null}
        title={options?.title || "Conferma azione"}
        description={options?.description || ""}
        confirmLabel={options?.confirmLabel}
        tone={options?.tone}
        onCancel={() => settle(false)}
        onConfirm={() => settle(true)}
      />
    ),
  };
}

export { useConfirmationDialog };
