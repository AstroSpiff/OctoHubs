import { createContext, useContext } from "react";

type WorkspaceCapabilities = {
  canMutate: boolean;
};

const WorkspaceCapabilitiesContext = createContext<WorkspaceCapabilities>({ canMutate: true });

function useWorkspaceCapabilities() {
  return useContext(WorkspaceCapabilitiesContext);
}

export { WorkspaceCapabilitiesContext, useWorkspaceCapabilities };
export type { WorkspaceCapabilities };
