import { ProbeComboCard } from "@/features/probe/components/probe-combo-card";
import type { ProbeComboServerStatus } from "@/features/probe/components/probe-combo-card";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import { ProbeWorkerCard } from "@/features/probe/components/probe-worker-card";
import { probeProgress } from "@/features/probe/presentation";
import type { ProbeServer, ProbeWorkerStatus } from "@/features/probe/types";

type RecentProbeControlsProps = {
  allServersSelected: boolean;
  serverCount: number;
  selectedServer?: ProbeServer;
  comboStatus?: ProbeWorkerStatus;
  discoveryStatus?: ProbeWorkerStatus;
  processingStatus?: ProbeWorkerStatus;
  comboServerStatuses: ProbeComboServerStatus[];
  disabled: boolean;
  canMutate?: boolean;
  onRunCombo: (mode: "smart" | "forced") => void;
  onStopCombo: () => void;
  onRunDiscovery: () => void;
  onStopDiscovery: () => void;
  onRunProcessing: (mode: "smart" | "forced") => void;
  onStopProcessing: () => void;
};

function RecentProbeControls({
  allServersSelected,
  serverCount,
  selectedServer,
  comboStatus,
  discoveryStatus,
  processingStatus,
  comboServerStatuses,
  disabled,
  canMutate = true,
  onRunCombo,
  onStopCombo,
  onRunDiscovery,
  onStopDiscovery,
  onRunProcessing,
  onStopProcessing,
}: RecentProbeControlsProps) {
  const comboRunning = Boolean(comboStatus?.running);
  const discoveryRunning = Boolean(discoveryStatus?.running);
  const processingRunning = Boolean(processingStatus?.running);

  return (
    <>
      <div className="probe-workers-grid">
        <ProbeComboCard
          scope="recent"
          status={comboStatus}
          serverStatuses={comboServerStatuses}
          actions={[
            {
              label: "Smart",
              icon: "play",
              variant: "primary",
              onClick: () => onRunCombo("smart"),
              disabled: disabled || comboRunning,
            },
            {
              label: "Forzato",
              icon: "zap",
              onClick: () => onRunCombo("forced"),
              disabled: disabled || comboRunning,
            },
            {
              label: "Ferma",
              icon: "stop",
              variant: "secondary",
              onClick: onStopCombo,
              disabled: disabled || !comboRunning,
            },
          ]}
          canMutate={canMutate}
        />
        <ProbeWorkerCard
          className="probe-worker-card--discovery"
          title="Individuazione ultimi aggiunti"
          description="Usa lo storico Emby per comporre una coda incrementale."
          status={discoveryStatus}
          headerDivider
          headerActions={
            <span className="probe-worker-context">
              {allServersSelected ? (
                <>{serverCount} server</>
              ) : selectedServer ? (
                <>
                  <EmbyServerIcon
                    icon={selectedServer.icon}
                    iconStyle={selectedServer.icon_style}
                    color={selectedServer.icon_color}
                    size={13}
                  />
                  {selectedServer.name}
                </>
              ) : null}
            </span>
          }
          stats={[
            { label: "Trovati", value: discoveryStatus?.found || 0 },
            {
              label: "Scansionati",
              value: discoveryStatus?.total_scanned || 0,
            },
          ]}
          actions={[
            {
              label: "Avvia",
              icon: "play",
              variant: "primary",
              onClick: onRunDiscovery,
              disabled: disabled || comboRunning || discoveryRunning,
            },
            {
              label: "Ferma",
              icon: "stop",
              variant: "secondary",
              onClick: onStopDiscovery,
              disabled: disabled || !discoveryRunning,
            },
          ]}
          canMutate={canMutate}
        />
        <ProbeWorkerCard
          className="probe-worker-card--processing"
          title="Analisi ultimi aggiunti"
          description="Elabora i recenti in modalità smart o senza pause."
          status={processingStatus}
          headerDivider
          progress={probeProgress(processingStatus)}
          stats={[
            { label: "Processati", value: processingStatus?.processed || 0 },
            { label: "Incompleti", value: processingStatus?.incomplete || 0 },
            { label: "Errori", value: processingStatus?.errors || 0 },
            { label: "In coda", value: processingStatus?.total || 0 },
          ]}
          actions={[
            {
              label: "Smart",
              icon: "play",
              variant: "primary",
              onClick: () => onRunProcessing("smart"),
              disabled: disabled || comboRunning || processingRunning,
            },
            {
              label: "Forzato",
              icon: "zap",
              onClick: () => onRunProcessing("forced"),
              disabled: disabled || comboRunning || processingRunning,
            },
            {
              label: "Ferma",
              icon: "stop",
              variant: "secondary",
              onClick: onStopProcessing,
              disabled: disabled || !processingRunning,
            },
          ]}
          canMutate={canMutate}
        />
      </div>
    </>
  );
}

export { RecentProbeControls };
