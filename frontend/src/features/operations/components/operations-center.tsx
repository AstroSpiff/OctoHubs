import { OperationsCenterView } from "@/features/operations/components/operations-center-view";
import { useOperations } from "@/features/operations/use-operations";

function OperationsCenter() {
  const { operations, clearCompleted, stopActiveWorkflow } = useOperations();

  return <OperationsCenterView
    operations={operations.data?.operations || []}
    activeCount={operations.data?.active_count || 0}
    fetching={operations.isFetching}
    clearing={clearCompleted.isPending}
    stopping={stopActiveWorkflow.isPending}
    error={operations.error || clearCompleted.error || stopActiveWorkflow.error}
    onRefresh={() => void operations.refetch()}
    onClear={() => clearCompleted.mutate()}
    onStop={() => stopActiveWorkflow.mutate()}
    storageKey="octohubs.operations.open"
    label="Operazioni applicazione"
  />;
}

export { OperationsCenter };
