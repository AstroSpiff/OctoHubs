import { ArrowDownUp, FolderCog, RefreshCw } from "@/components/ui/icons";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage, WorkspaceSection } from "@/components/ui/workspace-layout";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";
import { LibrariesBoard } from "@/features/libraries/components/libraries-board";
import { LibraryAssociationDialog } from "@/features/libraries/components/library-association-dialog";
import { LibraryMaintenance } from "@/features/libraries/components/library-maintenance";
import { LibraryOrderDialog } from "@/features/libraries/components/library-order-dialog";
import { LibraryScanHistory } from "@/features/libraries/components/library-scan-history";
import { LibrariesToolbar } from "@/features/libraries/components/libraries-toolbar";
import { LibraryWorkflowMode } from "@/features/libraries/components/library-workflow-mode";
import {
  defaultLibraryFilters,
  visibleLibraryGroups,
} from "@/features/libraries/presentation";
import type {
  LibraryEntry,
  LibraryFilters,
  LibraryGroup,
  LibraryScanHistoryJob,
} from "@/features/libraries/types";
import { useLibraries } from "@/features/libraries/use-libraries";

function LibrariesPage() {
  const [filters, setFilters] = useState<LibraryFilters>(defaultLibraryFilters);
  const confirmation = useConfirmationDialog();
  const [associationsOpen, setAssociationsOpen] = useState(false);
  const [orderOpen, setOrderOpen] = useState(false);
  const [drafts, setDrafts] = useState({ associations: false, order: false });
  const [workflowMode, setWorkflowMode] = useState(
    () =>
      window.localStorage.getItem("octohubs.library-workflow-mode") !== "false",
  );
  const libraries = useLibraries();
  const hasUnsavedChanges = drafts.associations || drafts.order;
  useBeforeUnloadWarning(hasUnsavedChanges);
  useUnsavedChangesNavigationGuard(hasUnsavedChanges, confirmation.confirm);
  const updateAssociationDirty = useCallback((associations: boolean) => {
    setDrafts((current) =>
      current.associations === associations
        ? current
        : { ...current, associations },
    );
  }, []);
  const updateOrderDirty = useCallback((order: boolean) => {
    setDrafts((current) =>
      current.order === order ? current : { ...current, order },
    );
  }, []);
  const groups = useMemo(
    () => libraries.groups.data?.groups || [],
    [libraries.groups.data],
  );
  const orderReady =
    libraries.groups.isSuccess && libraries.actionTargets.isSuccess;
  const visible = useMemo(
    () => visibleLibraryGroups(groups, filters),
    [groups, filters],
  );
  const error =
    libraries.groups.error ||
    libraries.activeJobs.error ||
    libraries.activeScans.error ||
    libraries.history.error ||
    libraries.associations.error ||
    libraries.actionTargets.error ||
    libraries.scan.error ||
    libraries.libraryScan.error ||
    libraries.saveAssociations.error ||
    libraries.saveGroupOrder.error ||
    libraries.saveServerOrder.error ||
    libraries.action.error ||
    libraries.resetHistory.error ||
    libraries.deleteHistoryJob.error ||
    libraries.workflow.error;
  const actionResult = libraries.action.data;

  function runMaintenance(
    action: "refresh_libraries" | "refresh_metadata",
    serverId?: string,
  ) {
    if (workflowMode && action === "refresh_libraries") {
      libraries.workflow.mutate(serverId ? { server_id: serverId } : {});
      return;
    }
    libraries.action.mutate({ action, serverId });
  }

  useEffect(() => {
    window.localStorage.setItem(
      "octohubs.library-workflow-mode",
      String(workflowMode),
    );
  }, [workflowMode]);

  function startGroupScan(
    group: LibraryGroup,
    scanType: "content" | "metadata",
  ) {
    if (!workflowMode || scanType === "metadata") {
      libraries.scan.mutate({ group, scanType });
      return;
    }
    libraries.workflow.mutate({
      group_name: group.group_name,
      scan_type: scanType,
      libraries: group.libraries
        .map((library) => ({
          server_id: library.server_id,
          library_id: library.library_id || library.id || "",
        }))
        .filter((library) => library.library_id),
    });
  }

  function startSingleLibraryScan(
    library: LibraryEntry,
    scanType: "content" | "metadata",
  ) {
    if (!workflowMode || scanType === "metadata") {
      libraries.libraryScan.mutate({ library, scanType });
      return;
    }
    const libraryId = library.library_id || library.id;
    if (!libraryId) return;
    libraries.workflow.mutate({
      group_name: library.library_name || "Libreria",
      scan_type: scanType,
      server_id: library.server_id,
      library_id: libraryId,
      libraries: [{ server_id: library.server_id, library_id: libraryId }],
    });
  }

  async function resetHistory() {
    if (!await confirmation.confirm({
      title: "Reimposta storico librerie",
      description: "Azzerare lo stato tracciato di scansioni e metadata? Le nuove operazioni ripartiranno senza storico.",
      confirmLabel: "Reimposta storico",
      tone: "danger",
    })) return;
    libraries.resetHistory.mutate();
  }

  async function deleteHistoryJob(job: LibraryScanHistoryJob) {
    const label = job.group_name || job.server_id || "questa operazione";
    if (
      !(await confirmation.confirm({
        title: "Elimina dalla cronologia",
        description: `Rimuovere ${label} dalla cronologia delle scansioni? L'operazione Emby non verrà modificata.`,
        confirmLabel: "Elimina voce",
        tone: "danger",
      }))
    )
      return;
    libraries.deleteHistoryJob.mutate(job.id);
  }

  async function saveAssociations(
    associations: Parameters<typeof libraries.saveAssociations.mutateAsync>[0],
  ) {
    await libraries.saveAssociations.mutateAsync(associations);
  }

  async function saveGroupOrder(
    order: Parameters<typeof libraries.saveGroupOrder.mutateAsync>[0],
  ) {
    await libraries.saveGroupOrder.mutateAsync(order);
  }

  async function saveServerOrder(
    serverIds: Parameters<typeof libraries.saveServerOrder.mutateAsync>[0],
  ) {
    await libraries.saveServerOrder.mutateAsync(serverIds);
  }

  const scanLibraryKey = libraries.libraryScan.isPending && libraries.libraryScan.variables
    ? `${libraries.libraryScan.variables.library.server_id}:${libraries.libraryScan.variables.library.library_id || libraries.libraryScan.variables.library.id || ""}`
    : undefined;

  return (
    <WorkspacePage>
      <WorkspaceSection
        className="libraries-workspace"
        aria-labelledby="libraries-single-title"
      >
        <WorkspaceHeading
          actionsClassName="libraries-workspace-actions"
          className="libraries-workspace-header"
          level="section"
          title="Librerie"
          titleId="libraries-single-title"
          description="Gestisci e scansiona le librerie raggruppate tra più server Emby."
          actions={<>
            <LibraryWorkflowMode
              enabled={workflowMode}
              onChange={setWorkflowMode}
            />
            <Button
              type="button"
              requiresWriteAccess
              variant="secondary"
              size="compact"
              onClick={() => setAssociationsOpen(true)}
            >
              <FolderCog size={16} aria-hidden="true" />
              Associazioni
            </Button>
            <Button
              type="button"
              requiresWriteAccess
              variant="secondary"
              size="icon"
              title="Organizza gruppi e server"
              aria-label="Organizza gruppi e server"
              onClick={() => setOrderOpen(true)}
              disabled={!orderReady}
            >
              <ArrowDownUp size={16} aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              title="Aggiorna librerie"
              aria-label="Aggiorna librerie"
              onClick={() => void libraries.refresh()}
              disabled={libraries.groups.isFetching}
            >
              <RefreshCw
                size={16}
                className={libraries.groups.isFetching ? "animate-spin" : ""}
                aria-hidden="true"
              />
            </Button>
          </>}
        />

        {error ? (
          <div className="inline-alert inline-alert--error" role="alert">
            {error.message}
          </div>
        ) : null}
        {libraries.scan.isSuccess ? (
          <div className="inline-alert inline-alert--success" role="status">
            Scansione del gruppo avviata. Lo stato si aggiorna automaticamente.
          </div>
        ) : null}
        {libraries.libraryScan.isSuccess ? (
          <div className="inline-alert inline-alert--success" role="status">
            Scansione della libreria avviata. Lo stato si aggiorna
            automaticamente.
          </div>
        ) : null}
        {libraries.workflow.isSuccess ? (
          <div className="inline-alert inline-alert--success" role="status">
            {libraries.workflow.data.message ||
              "Workflow della libreria avviato."}
          </div>
        ) : null}
        {actionResult ? (
          <div
            className={`inline-alert ${actionResult.success ? "inline-alert--success" : "inline-alert--error"}`}
            role="status"
          >
            {actionResult.message}
          </div>
        ) : null}
        {libraries.resetHistory.isSuccess ? (
          <div className="inline-alert inline-alert--success" role="status">
            {libraries.resetHistory.data.message}
          </div>
        ) : null}
        <LibrariesToolbar
          filters={filters}
          onChange={(updates) =>
            setFilters((current) => ({ ...current, ...updates }))
          }
        />
        <LibrariesBoard
          groups={visible}
          workflowMode={workflowMode}
          scanningId={
            (libraries.scan.isPending
              ? libraries.scan.variables?.group.group_name
              : undefined) ||
            (libraries.workflow.isPending
              ? libraries.workflow.variables?.group_name
              : undefined)
          }
          scanJobs={libraries.activeJobs.data?.jobs || []}
          scanHistory={libraries.history.data?.jobs || []}
          scanningLibraryKey={scanLibraryKey}
          libraryScanBusy={
            libraries.libraryScan.isPending || libraries.workflow.isPending
          }
          onScan={startGroupScan}
          onScanLibrary={startSingleLibraryScan}
        />

        <LibraryMaintenance
          servers={libraries.actionTargets.data?.servers || []}
          activeScans={libraries.activeScans.data?.active_scans || []}
          busy={
            libraries.action.isPending ? libraries.action.variables : undefined
          }
          workflowBusy={libraries.workflow.isPending}
          workflowMode={workflowMode}
          onWorkflowModeChange={setWorkflowMode}
          onRun={runMaintenance}
        />
        <LibraryScanHistory
          jobs={libraries.history.data?.jobs || []}
          loading={libraries.history.isFetching}
          resetting={libraries.resetHistory.isPending}
          deletingId={
            libraries.deleteHistoryJob.isPending
              ? libraries.deleteHistoryJob.variables
              : undefined
          }
          onRefresh={() => void libraries.history.refetch()}
          onReset={resetHistory}
          onDelete={(job) => void deleteHistoryJob(job)}
        />
      </WorkspaceSection>
      <LibraryAssociationDialog
        open={associationsOpen}
        ready={libraries.groups.isSuccess && libraries.associations.isSuccess}
        groups={groups}
        associations={libraries.associations.data?.associations || []}
        saving={libraries.saveAssociations.isPending}
        onDirtyChange={updateAssociationDirty}
        onClose={() => setAssociationsOpen(false)}
        onSave={saveAssociations}
      />
      <LibraryOrderDialog
        open={orderOpen}
        ready={orderReady}
        groups={groups}
        servers={libraries.actionTargets.data?.servers || []}
        savingGroups={libraries.saveGroupOrder.isPending}
        savingServers={libraries.saveServerOrder.isPending}
        onDirtyChange={updateOrderDirty}
        onClose={() => setOrderOpen(false)}
        onSaveGroupOrder={saveGroupOrder}
        onSaveServerOrder={saveServerOrder}
      />
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { LibrariesPage };
