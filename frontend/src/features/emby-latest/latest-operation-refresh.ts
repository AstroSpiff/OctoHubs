import { isActiveOperation } from "@/features/operations/presentation";
import type { Operation } from "@/features/operations/types";

const latestOperationKinds = new Set(["workflow", "latest_refresh", "latest_notify"]);

function hasActiveLatestWorkflow(operations: Operation[]) {
  return operations.some(
    (operation) => operation.kind === "workflow" && isActiveOperation(operation),
  );
}

function completedLatestOperations(previous: Operation[], current: Operation[]) {
  const previousById = new Map(previous.map((operation) => [operation.id, operation]));
  return current.filter((operation) => {
    if (!latestOperationKinds.has(operation.kind) || isActiveOperation(operation))
      return false;
    const previousOperation = previousById.get(operation.id);
    return !previousOperation || isActiveOperation(previousOperation);
  });
}

export { completedLatestOperations, hasActiveLatestWorkflow };
