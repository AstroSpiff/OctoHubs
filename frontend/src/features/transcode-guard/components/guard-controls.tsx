import { RefreshCw, ScanSearch } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { cn } from "@/lib/utils";

function GuardControls({
  running,
  stateReady,
  checking,
  changingState,
  refreshing,
  error,
  onCheck,
  onStateChange,
  onRefresh,
}: {
  running: boolean;
  stateReady: boolean;
  checking: boolean;
  changingState: boolean;
  refreshing: boolean;
  error?: Error | null;
  onCheck: () => void;
  onStateChange: (running: boolean) => void;
  onRefresh: () => void;
}) {
  const busy = checking || changingState;
  return (
    <div className="guard-controls-panel">
      <div className="guard-controls">
        <Button type="button" variant="ghost" size="icon" title="Aggiorna stato" aria-label="Aggiorna stato" onClick={onRefresh} disabled={refreshing || busy}>
          <RefreshCw className={cn(refreshing && "animate-spin")} size={16} aria-hidden="true" />
        </Button>
        <Button type="button" requiresWriteAccess variant="ghost" size="compact" onClick={onCheck} disabled={busy}>
          <ScanSearch className={cn(checking && "animate-spin")} size={15} aria-hidden="true" />
          {checking ? "Verifica in corso..." : "Verifica ora"}
        </Button>
        <WriteAction>
          <label className="guard-controls-toggle" title="Avvia o ferma il monitor automatico di Transcode Guard.">
            <span>Attiva</span>
            <input
              type="checkbox"
              checked={running}
              disabled={busy || !stateReady}
              onChange={(event) => onStateChange(event.target.checked)}
            />
          </label>
        </WriteAction>
      </div>
      {error ? <p className="guard-action-feedback guard-action-feedback--error" role="alert">{error.message}</p> : null}
    </div>
  );
}

export { GuardControls };
