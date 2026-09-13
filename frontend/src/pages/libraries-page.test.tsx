// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ConfirmationOptions } from "@/components/ui/confirmation-dialog";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { useLibraries } from "@/features/libraries/use-libraries";
import { LibrariesPage } from "@/pages/libraries-page";

vi.mock("@/components/ui/use-confirmation-dialog", () => ({
  useConfirmationDialog: vi.fn(),
}));
vi.mock("@/features/libraries/use-libraries", () => ({
  useLibraries: vi.fn(),
}));
vi.mock("@/lib/use-before-unload-warning", () => ({
  useBeforeUnloadWarning: vi.fn(),
}));
vi.mock("@/lib/use-unsaved-changes-navigation-guard", () => ({
  useUnsavedChangesNavigationGuard: vi.fn(),
}));
vi.mock("@/components/ui/query-state-boundary", () => ({
  QueryStateBoundary: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/features/libraries/components/libraries-toolbar", () => ({
  LibrariesToolbar: () => null,
}));
vi.mock("@/features/libraries/components/library-scan-history", () => ({
  LibraryScanHistory: () => null,
}));
vi.mock("@/features/libraries/components/library-association-dialog", () => ({
  LibraryAssociationDialog: () => null,
}));
vi.mock("@/features/libraries/components/library-order-dialog", () => ({
  LibraryOrderDialog: () => null,
}));
vi.mock("@/features/libraries/components/library-workflow-mode", () => ({
  LibraryWorkflowMode: () => null,
}));
vi.mock("@/features/libraries/components/libraries-board", () => ({
  LibrariesBoard: ({ groups, onScan, onScanLibrary }: {
    groups: Array<{ group_name: string; libraries: Array<Record<string, string>> }>;
    onScan: (group: unknown, scanType: "metadata") => void;
    onScanLibrary: (library: unknown, scanType: "metadata") => void;
  }) => <>
    <button type="button" aria-label="metadata-gruppo" onClick={() => onScan(groups[0], "metadata")} />
    <button type="button" aria-label="metadata-libreria" onClick={() => onScanLibrary(groups[0].libraries[0], "metadata")} />
  </>,
}));
vi.mock("@/features/libraries/components/library-maintenance", () => ({
  LibraryMaintenance: ({ onRun }: {
    onRun: (action: "refresh_metadata", serverId?: string) => void;
  }) => <>
    <button type="button" aria-label="metadata-tutti" onClick={() => onRun("refresh_metadata")} />
    <button type="button" aria-label="metadata-server" onClick={() => onRun("refresh_metadata", "server-1")} />
  </>,
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const group = {
  group_name: "Film condivisi",
  collection_type: "movies",
  servers: ["server-1"],
  libraries: [{
    server_id: "server-1",
    server_name: "Green",
    library_id: "library-1",
    library_name: "Film",
  }],
};

describe("LibrariesPage metadata refresh confirmation", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let confirm: ReturnType<
    typeof vi.fn<(options: ConfirmationOptions) => Promise<boolean>>
  >;
  let state: ReturnType<typeof libraryState>;

  beforeEach(async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    confirm = vi.fn<(options: ConfirmationOptions) => Promise<boolean>>();
    state = libraryState();
    vi.mocked(useConfirmationDialog).mockReturnValue({ confirm, dialog: <></> });
    vi.mocked(useLibraries).mockReturnValue(state as never);
    await act(async () => root.render(<LibrariesPage />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it.each([
    ["metadata-tutti", "tutti i server Emby abilitati"],
    ["metadata-server", "il server “Green”"],
    ["metadata-gruppo", "il gruppo “Film condivisi”"],
    ["metadata-libreria", "la libreria “Film” sul server “Green”"],
  ])("blocks %s when the destructive confirmation is cancelled", async (label, target) => {
    confirm.mockResolvedValue(false);

    await click(container, label);

    expect(confirm).toHaveBeenCalledOnce();
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({
      title: "Aggiornamento metadata completo",
      description: expect.stringContaining(target),
      confirmLabel: "Aggiorna e cancella i probe",
      tone: "danger",
    }));
    expect(confirm.mock.calls[0][0].description).toContain("cancella tutti i probe dei file coinvolti");
    expect(confirm.mock.calls[0][0].description).toContain("eseguire nuovamente Media Probe");
    expect(state.action.mutate).not.toHaveBeenCalled();
    expect(state.scan.mutate).not.toHaveBeenCalled();
    expect(state.libraryScan.mutate).not.toHaveBeenCalled();
  });

  it("starts each metadata operation only after an affirmative confirmation", async () => {
    confirm.mockResolvedValue(true);

    await click(container, "metadata-tutti");
    await click(container, "metadata-server");
    await click(container, "metadata-gruppo");
    await click(container, "metadata-libreria");

    expect(confirm).toHaveBeenCalledTimes(4);
    expect(state.action.mutate).toHaveBeenNthCalledWith(1, {
      action: "refresh_metadata",
      serverId: undefined,
    });
    expect(state.action.mutate).toHaveBeenNthCalledWith(2, {
      action: "refresh_metadata",
      serverId: "server-1",
    });
    expect(state.scan.mutate).toHaveBeenCalledWith({ group, scanType: "metadata" });
    expect(state.libraryScan.mutate).toHaveBeenCalledWith({
      library: group.libraries[0],
      scanType: "metadata",
    });
  });
});

async function click(container: HTMLElement, label: string) {
  const button = container.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`);
  if (!button) throw new Error(`missing ${label}`);
  await act(async () => {
    button.click();
    await Promise.resolve();
  });
}

function libraryState() {
  const query = (data: unknown) => ({
    data,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
  });
  const mutation = () => ({
    data: undefined,
    error: null,
    isPending: false,
    isSuccess: false,
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
  });
  return {
    groups: query({ groups: [group] }),
    activeJobs: query({ jobs: [] }),
    activeScans: query({ active_scans: [] }),
    history: query({ jobs: [] }),
    associations: query({ associations: [] }),
    actionTargets: query({
      servers: [{ id: "server-1", name: "Green" }],
    }),
    scan: mutation(),
    libraryScan: mutation(),
    saveAssociations: mutation(),
    saveGroupOrder: mutation(),
    saveServerOrder: mutation(),
    action: mutation(),
    resetHistory: mutation(),
    deleteHistoryJob: mutation(),
    workflow: mutation(),
    groupScanOperations: { errors: {}, pendingKeys: new Set<string>() },
    libraryScanOperations: { errors: {}, pendingKeys: new Set<string>() },
    workflowMaintenanceOperations: { errors: {}, pendingKeys: new Set<string>() },
    historyDeleteOperations: { errors: {}, pendingKeys: new Set<string>() },
    refresh: vi.fn(),
  };
}
