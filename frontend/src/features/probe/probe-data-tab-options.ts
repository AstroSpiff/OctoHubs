type ProbeDataTab = "queue" | "history" | "errors" | "incomplete" | "settings";

type ProbeDataTabOption = {
  id: ProbeDataTab;
  label: string;
  count?: number;
};

function probeDataTabOptions({
  queueCount,
  historyCount,
  errorCount,
  incompleteCount,
  showSettings,
}: {
  queueCount: number;
  historyCount: number;
  errorCount: number;
  incompleteCount: number;
  showSettings: boolean;
}): ProbeDataTabOption[] {
  return [
    { id: "queue", label: "Coda", count: queueCount },
    { id: "history", label: "Storico", count: historyCount },
    { id: "errors", label: "Errori", count: errorCount },
    { id: "incomplete", label: "Incompleti", count: incompleteCount },
    ...(showSettings ? [{ id: "settings" as const, label: "Configurazione" }] : []),
  ];
}

export { probeDataTabOptions };
export type { ProbeDataTab, ProbeDataTabOption };
