import { type ReactNode } from "react";

import {
  WorkspaceCapabilitiesContext,
  useWorkspaceCapabilities,
  type WorkspaceCapabilities,
} from "@/features/session/workspace-capabilities-context";

function WorkspaceCapabilitiesProvider({
  canMutate,
  children,
}: WorkspaceCapabilities & { children: ReactNode }) {
  return (
    <WorkspaceCapabilitiesContext.Provider value={{ canMutate }}>
      {children}
    </WorkspaceCapabilitiesContext.Provider>
  );
}

function WriteAction({ children }: { children: ReactNode }) {
  const { canMutate } = useWorkspaceCapabilities();
  return canMutate ? children : null;
}

export { WorkspaceCapabilitiesProvider, WriteAction };
