import { WriteAction } from "@/features/session/workspace-capabilities";

type LibraryWorkflowModeProps = {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  compact?: boolean;
};

function LibraryWorkflowMode({
  enabled,
  onChange,
  compact = false,
}: LibraryWorkflowModeProps) {
  return (
    <WriteAction>
      <label
        className={`libraries-workflow-mode${compact ? " is-compact" : ""}`}
        title="Le scansioni singole avviano il workflow intelligente completo"
      >
        <span className="libraries-workflow-mode-copy">
          <strong>Modalità Workflow Completo</strong>
          {compact ? null : <small>Scansione, probe e pubblicazioni.</small>}
        </span>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onChange(event.target.checked)}
          aria-label="Modalità Workflow Completo"
        />
        <span className="libraries-workflow-mode-slider" aria-hidden="true" />
      </label>
    </WriteAction>
  );
}

export { LibraryWorkflowMode };
