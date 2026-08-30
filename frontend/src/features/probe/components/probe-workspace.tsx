import { FlaskConical } from "@/components/ui/icons";
import type { ReactNode } from "react";

import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspaceSection } from "@/components/ui/workspace-layout";
import { ProbeServerTabs } from "@/features/probe/components/probe-server-tabs";
import { probeScopeLabel } from "@/features/probe/presentation";
import type { ProbeScope, ProbeServer } from "@/features/probe/types";

function probeScopeDescription(scope: ProbeScope) {
  return scope === "libraries"
    ? "Analizza e recupera i file video delle librerie selezionate."
    : "Controlla e recupera i contenuti aggiunti di recente sui server selezionati.";
}

type ProbeWorkspaceProps = {
  scope: ProbeScope;
  servers: ProbeServer[];
  serverId: string;
  onServerChange: (serverId: string) => boolean | void | Promise<boolean | void>;
  children: ReactNode;
};

function ProbeWorkspace({
  scope,
  servers,
  serverId,
  onServerChange,
  children,
}: ProbeWorkspaceProps) {
  return (
    <WorkspaceSection
      id={`probe-${scope}-workspace`}
      className="probe-workspace"
      aria-labelledby="probe-workspace-title"
      tabIndex={-1}
    >
      <WorkspaceHeading
        level="section"
        leading={<FlaskConical size={18} aria-hidden="true" />}
        titleId="probe-workspace-title"
        title={probeScopeLabel(scope)}
        description={probeScopeDescription(scope)}
        actions={<ProbeServerTabs
          servers={servers}
          value={serverId}
          allowAll={scope === "recent"}
          onChange={onServerChange}
        />}
      />
      {children}
    </WorkspaceSection>
  );
}

export { ProbeWorkspace };
