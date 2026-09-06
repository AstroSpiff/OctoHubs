import {
  ChevronDown,
  ListChecks,
  RefreshCw,
  Square,
  Trash2,
} from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import {
  formatOperationTimestamp,
  isActiveOperation,
  operationCanStop,
  operationDetailTags,
  operationStatusLabel,
  operationStatusSeverity,
  operationWorkflowSteps,
} from "@/features/operations/presentation";
import type {
  Operation,
  OperationWorkflowStep,
} from "@/features/operations/types";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import {
  browserLocalStorage,
  readStoredValue,
  writeStoredValue,
} from "@/lib/safe-web-storage";
import { cn } from "@/lib/utils";

type OperationsCenterViewProps = {
  operations: Operation[];
  activeCount: number;
  fetching: boolean;
  clearing?: boolean;
  stopping?: boolean;
  error?: Error | null;
  onRefresh: () => void;
  onClear: () => void;
  onStop?: () => void;
  storageKey: string;
  label: string;
  className?: string;
};

function OperationsCenterView({
  operations,
  activeCount,
  fetching,
  clearing = false,
  stopping = false,
  error,
  onRefresh,
  onClear,
  onStop,
  storageKey,
  label,
  className,
}: OperationsCenterViewProps) {
  const confirmation = useConfirmationDialog();
  const { canMutate } = useWorkspaceCapabilities();
  const [open, setOpen] = useState(
    () => readStoredValue(browserLocalStorage(), storageKey) === "true",
  );
  const previousErrorRef = useRef<Error | null | undefined>(undefined);
  const completedCount = operations.filter(
    (operation) => !isActiveOperation(operation),
  ).length;

  useEffect(() => {
    writeStoredValue(browserLocalStorage(), storageKey, open ? "true" : "false");
  }, [open, storageKey]);

  useEffect(() => {
    if (error && !previousErrorRef.current && !operations.length) setOpen(true);
    previousErrorRef.current = error;
  }, [error, operations.length]);

  if (!operations.length && !error) return null;
  const panelOpen = open;

  async function requestStopWorkflow() {
    if (
      !onStop ||
      !(await confirmation.confirm({
        title: "Interrompi workflow",
        description:
          "Vuoi interrompere il workflow in corso? Le attività già completate non verranno annullate.",
        confirmLabel: "Interrompi",
        tone: "danger",
      }))
    )
      return;
    onStop();
  }

  async function requestClearCompleted() {
    if (
      !(await confirmation.confirm({
        title: "Pulisci operazioni completate",
        description:
          "Le operazioni completate, interrotte o con errore verranno rimosse da questa lista.",
        confirmLabel: "Pulisci elenco",
        tone: "danger",
      }))
    )
      return;
    onClear();
  }

  return (
    <aside
      className={cn(
        "operations-center",
        activeCount > 0 && "has-active",
        className,
      )}
      aria-label={label}
    >
      {panelOpen ? (
        <section
          className="operations-center-panel"
          aria-label={`${label} recenti`}
        >
          <header className="operations-center-header">
            <div>
              <strong>{label}</strong>
              <span>
                {error && !operations.length
                  ? "Caricamento non riuscito"
                  : activeCount
                  ? `${activeCount} in corso`
                  : `${operations.length} recenti`}
              </span>
            </div>
            <div className="operations-center-actions">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                title={`Aggiorna ${label.toLowerCase()}`}
                aria-label={`Aggiorna ${label.toLowerCase()}`}
                onClick={onRefresh}
                disabled={fetching}
              >
                <RefreshCw
                  size={15}
                  className={cn(fetching && "animate-spin")}
                  aria-hidden="true"
                />
              </Button>
              {canMutate ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  title="Pulisci operazioni completate"
                  aria-label="Pulisci operazioni completate"
                  onClick={() => void requestClearCompleted()}
                  disabled={!completedCount || clearing}
                >
                  <Trash2 size={15} aria-hidden="true" />
                </Button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                title={`Riduci ${label.toLowerCase()}`}
                aria-label={`Riduci ${label.toLowerCase()}`}
                onClick={() => setOpen(false)}
              >
                <ChevronDown size={17} aria-hidden="true" />
              </Button>
            </div>
          </header>
          {error ? (
            <p className="operations-center-error" role="alert">
              {error.message}
            </p>
          ) : null}
          <div className="operations-center-list">
            {operations.slice(0, 14).map((operation) => (
              <OperationItem
                key={operation.id}
                operation={operation}
                stopping={stopping}
                onStop={canMutate && onStop ? () => void requestStopWorkflow() : undefined}
              />
            ))}
          </div>
        </section>
      ) : null}
      <Button
        type="button"
        className="operations-center-toggle"
        variant="secondary"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={panelOpen}
        aria-label={
          open ? `Riduci ${label.toLowerCase()}` : `Apri ${label.toLowerCase()}`
        }
      >
        <ListChecks size={17} aria-hidden="true" />
        Operazioni
        <strong>{activeCount || operations.length}</strong>
      </Button>
      {confirmation.dialog}
    </aside>
  );
}

function OperationItem({
  operation,
  stopping,
  onStop,
}: {
  operation: Operation;
  stopping: boolean;
  onStop?: () => void;
}) {
  const active = isActiveOperation(operation);
  const tags = operationDetailTags(operation);
  const steps = operationWorkflowSteps(operation);
  const progress = Math.max(0, Math.min(100, Number(operation.progress) || 0));

  return (
    <article
      className={cn(
        "operations-center-item",
        `operations-center-item--${operation.status}`,
      )}
    >
      <div className="operations-center-item-header">
        <div>
          <strong>{operation.title || "Operazione"}</strong>
          <span>
            {operation.summary || operation.kind || "Attività applicazione"}
          </span>
        </div>
        <div className="operations-center-item-status">
          <StatusBadge severity={operationStatusSeverity(operation.status)}>
            {operationStatusLabel(operation.status)}
          </StatusBadge>
          {onStop && operationCanStop(operation) ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              title="Interrompi workflow"
              aria-label={`Interrompi ${operation.title || "workflow"}`}
              onClick={onStop}
              disabled={stopping}
            >
              <Square size={13} aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      </div>
      <p>
        {operation.error || operation.message || "Nessun dettaglio disponibile"}
      </p>
      {active ? (
        <div
          className="operations-center-progress"
          aria-label={`Avanzamento ${progress}%`}
        >
          <span>
            <i style={{ width: `${progress}%` }} />
          </span>
          <strong>{progress}%</strong>
        </div>
      ) : null}
      {steps.length ? (
        <div className="operations-center-steps">
          {steps.map((step, index) => (
            <WorkflowStep
              key={step.id || `${step.label}-${index}`}
              step={step}
            />
          ))}
        </div>
      ) : null}
      {tags.length ? (
        <div className="operations-center-tags">
          {tags.map((tag) => (
            <span key={tag.key}>{tag.value}</span>
          ))}
        </div>
      ) : null}
      <time dateTime={operation.updated_at}>
        Aggiornata {formatOperationTimestamp(operation.updated_at)}
      </time>
    </article>
  );
}

function WorkflowStep({ step }: { step: OperationWorkflowStep }) {
  const status = String(step.status || "pending");
  return (
    <div
      className={cn(
        "operations-center-step",
        `operations-center-step--${status}`,
      )}
    >
      <span aria-hidden="true" />{" "}
      <div>
        <strong>{step.label || "Passaggio workflow"}</strong>
        {step.details ? <small>{step.details}</small> : null}
      </div>
    </div>
  );
}

export { OperationsCenterView };
