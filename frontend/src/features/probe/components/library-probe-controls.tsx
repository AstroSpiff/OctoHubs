import { ProbeComboCard } from "@/features/probe/components/probe-combo-card";
import type { ProbeComboServerStatus } from "@/features/probe/components/probe-combo-card";
import { ProbeLibrarySelector } from "@/features/probe/components/probe-library-selector";
import { ProbeWorkerCard } from "@/features/probe/components/probe-worker-card";
import { probeProgress } from "@/features/probe/presentation";
import type { ProbeLibrary, ProbeWorkerStatus } from "@/features/probe/types";

type LibraryProbeControlsProps = {
  libraries: ProbeLibrary[];
  discoverySelected: string[];
  processingSelected: string[];
  discoveryStatus?: ProbeWorkerStatus;
  processingStatus?: ProbeWorkerStatus;
  comboStatus?: ProbeWorkerStatus;
  comboServerStatuses: ProbeComboServerStatus[];
  disabled: boolean;
  canMutate?: boolean;
  onDiscoverySelectionChange: (ids: string[]) => void;
  onProcessingSelectionChange: (ids: string[]) => void;
  onRunCombo: (mode: "smart" | "forced") => void;
  onStopCombo: () => void;
  onRunDiscovery: () => void;
  onStopDiscovery: () => void;
  onRunProcessing: (mode: "smart" | "forced") => void;
  onStopProcessing: () => void;
};

function LibraryProbeControls({
  libraries,
  discoverySelected,
  processingSelected,
  discoveryStatus,
  processingStatus,
  comboStatus,
  comboServerStatuses,
  disabled,
  canMutate = true,
  onDiscoverySelectionChange,
  onProcessingSelectionChange,
  onRunCombo,
  onStopCombo,
  onRunDiscovery,
  onStopDiscovery,
  onRunProcessing,
  onStopProcessing,
}: LibraryProbeControlsProps) {
  const comboRunning = Boolean(comboStatus?.running);
  const discoveryReady = discoverySelected.length > 0;
  const processingReady = processingSelected.length > 0;

  return (
    <div className="probe-workers-grid">
      <ProbeComboCard
        scope="libraries"
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
        title="Individuazione"
        description="Cerca i file candidati da aggiungere alla coda di analisi."
        status={discoveryStatus}
        stats={[
          { label: "Trovati", value: discoveryStatus?.found || 0 },
          { label: "Scansionati", value: discoveryStatus?.total_scanned || 0 },
        ]}
        actions={[
          {
            label: "Avvia",
            icon: "play",
            variant: "primary",
            onClick: onRunDiscovery,
            disabled:
              disabled ||
              comboRunning ||
              Boolean(discoveryStatus?.running) ||
              !discoveryReady,
            title: discoveryReady
              ? undefined
              : "Seleziona almeno una libreria prima di avviare l'individuazione",
          },
          {
            label: "Ferma",
            icon: "stop",
            variant: "secondary",
            onClick: onStopDiscovery,
            disabled: disabled || !discoveryStatus?.running,
          },
        ]}
        canMutate={canMutate}
      >
        <ProbeLibrarySelector
          libraries={libraries}
          selected={discoverySelected}
          disabled={
            disabled || comboRunning || Boolean(discoveryStatus?.running)
          }
          onChange={onDiscoverySelectionChange}
        />
      </ProbeWorkerCard>
      <ProbeWorkerCard
        className="probe-worker-card--processing"
        title="Analisi"
        description="Recupera e verifica i metadati degli elementi in coda."
        status={processingStatus}
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
            disabled:
              disabled ||
              comboRunning ||
              Boolean(processingStatus?.running) ||
              !processingReady,
            title: processingReady
              ? undefined
              : "Seleziona almeno una libreria prima di avviare l'analisi",
          },
          {
            label: "Forzato",
            icon: "zap",
            onClick: () => onRunProcessing("forced"),
            disabled:
              disabled ||
              comboRunning ||
              Boolean(processingStatus?.running) ||
              !processingReady,
            title: processingReady
              ? undefined
              : "Seleziona almeno una libreria prima di avviare l'analisi",
          },
          {
            label: "Ferma",
            icon: "stop",
            variant: "secondary",
            onClick: onStopProcessing,
            disabled: disabled || !processingStatus?.running,
          },
        ]}
        canMutate={canMutate}
      >
        <ProbeLibrarySelector
          libraries={libraries}
          selected={processingSelected}
          disabled={
            disabled || comboRunning || Boolean(processingStatus?.running)
          }
          onChange={onProcessingSelectionChange}
        />
      </ProbeWorkerCard>
    </div>
  );
}

export { LibraryProbeControls };
