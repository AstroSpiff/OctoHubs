import { RefreshCw } from "@/components/ui/icons";
import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspaceSection } from "@/components/ui/workspace-layout";
import { SystemStatusOverview } from "@/features/system-status/components/status-overview";
import { SystemStatusSection } from "@/features/system-status/components/status-presentation";
import { useSystemStatus } from "@/features/system-status/use-system-status";
import { cn } from "@/lib/utils";

function SystemStatusWorkspace({ embedded = false }: { embedded?: boolean }) {
  const status = useSystemStatus();
  const counts = useMemo(() => {
    const summary = { ok: 0, warning: 0, error: 0, unknown: 0 };
    status.sections
      .flatMap((section) => section.items)
      .forEach((item) => {
        summary[item.severity] += 1;
      });
    return summary;
  }, [status.sections]);

  return (
    <WorkspaceSection
      className={
        embedded
          ? "embedded-workspace system-status-workspace"
          : "system-status-workspace"
      }
    >
      <SystemStatusHeading
        embedded={embedded}
        refreshing={status.loading}
        onRefresh={() => void status.refreshAll()}
      />
      <SystemStatusOverview
        counts={counts}
        generatedAt={status.generatedAt}
        loading={status.loading}
      />
      {status.error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {status.error}
        </div>
      ) : null}
      {status.loading && !status.sections.length ? (
        <div className="loading-state">Caricamento stato sistema...</div>
      ) : null}
      <div className="status-sections">
        {status.sections.map((section) => (
          <SystemStatusSection
            key={section.id}
            section={section}
            refreshing={status.refreshingSections.has(section.id)}
            error={status.sectionErrors[section.id]}
            headingLevel={embedded ? "subsection" : "section"}
            onRefresh={(checkServices) =>
              void status.refreshSection(section.id, checkServices)
            }
          />
        ))}
      </div>
    </WorkspaceSection>
  );
}

function SystemStatusHeading({
  embedded,
  refreshing,
  onRefresh,
}: {
  embedded: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <WorkspaceHeading
      level={embedded ? "section" : "page"}
      context="Controllo operativo"
      title="Stato sistema"
      description="Informazioni verificate, aggiornamenti per area e collegamenti diretti ai dettagli operativi."
      actions={<Button
        type="button"
        variant="secondary"
        size="compact"
        onClick={onRefresh}
        disabled={refreshing}
      >
        <RefreshCw
          className={cn(refreshing && "animate-spin")}
          size={16}
          aria-hidden="true"
        />
        Aggiorna tutto
      </Button>}
    />
  );
}

export { SystemStatusWorkspace };
