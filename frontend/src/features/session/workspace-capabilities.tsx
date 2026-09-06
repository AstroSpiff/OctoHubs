import { type ReactNode } from "react";

import {
  WorkspaceCapabilitiesContext,
  useWorkspaceCapabilities,
  type WorkspaceCapabilities,
} from "@/features/session/workspace-capabilities-context";

function WorkspaceCapabilitiesProvider({
  accountId = null,
  canMutate,
  children,
}: Omit<WorkspaceCapabilities, "accountId"> & {
  accountId?: number | null;
  children: ReactNode;
}) {
  return (
    <WorkspaceCapabilitiesContext.Provider value={{ accountId, canMutate }}>
      {children}
    </WorkspaceCapabilitiesContext.Provider>
  );
}

function WriteAction({ children }: { children: ReactNode }) {
  const { canMutate } = useWorkspaceCapabilities();
  return canMutate ? children : null;
}

export { WorkspaceCapabilitiesProvider, WriteAction };
