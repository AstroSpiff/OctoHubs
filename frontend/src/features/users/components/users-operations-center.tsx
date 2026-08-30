import { OperationsCenterView } from "@/features/operations/components/operations-center-view";
import { useUserOperations } from "@/features/users/user-operations";

function UsersOperationsCenter() {
  const { operations, clearCompleted } = useUserOperations();
  return <OperationsCenterView
    operations={operations.data?.operations || []}
    activeCount={operations.data?.active_count || 0}
    fetching={operations.isFetching}
    clearing={clearCompleted.isPending}
    error={clearCompleted.error}
    onRefresh={() => void operations.refetch()}
    onClear={() => clearCompleted.mutate()}
    storageKey="octohubs.users.operations.open"
    label="Operazioni utenti"
    className="operations-center--users"
  />;
}

export { UsersOperationsCenter };
