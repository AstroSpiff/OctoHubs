import { RefreshCw } from "@/components/ui/icons";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

type QueryStateBoundaryProps = {
  children: ReactNode;
  error?: Error | null;
  hasData: boolean;
  loadingLabel: string;
  retrying?: boolean;
  onRetry: () => void;
};

function QueryStateBoundary({
  children,
  error,
  hasData,
  loadingLabel,
  onRetry,
  retrying = false,
}: QueryStateBoundaryProps) {
  if (error && !hasData) {
    return <QueryErrorNotice error={error} onRetry={onRetry} retrying={retrying} />;
  }
  if (!hasData) return <div className="loading-state" role="status">{loadingLabel}</div>;

  return (
    <>
      {error ? <QueryErrorNotice error={error} onRetry={onRetry} retrying={retrying} /> : null}
      {children}
    </>
  );
}

function QueryErrorNotice({
  error,
  onRetry,
  retrying,
}: {
  error: Error;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <div className="inline-alert inline-alert--error" role="alert">
      <span>{error.message}</span>
      <Button
        type="button"
        variant="secondary"
        size="compact"
        onClick={onRetry}
        disabled={retrying}
      >
        <RefreshCw
          size={14}
          className={retrying ? "animate-spin" : ""}
          aria-hidden="true"
        />
        {retrying ? "Nuovo tentativo..." : "Riprova"}
      </Button>
    </div>
  );
}

export { QueryStateBoundary };
