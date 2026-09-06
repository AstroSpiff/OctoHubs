import { createContext, useContext } from "react";

type WorkspaceCapabilities = {
  accountId: number | null;
  canMutate: boolean;
};

const WorkspaceCapabilitiesContext = createContext<WorkspaceCapabilities>({
  accountId: null,
  canMutate: true,
});

function useWorkspaceCapabilities() {
  return useContext(WorkspaceCapabilitiesContext);
}

export { WorkspaceCapabilitiesContext, useWorkspaceCapabilities };
export type { WorkspaceCapabilities };
