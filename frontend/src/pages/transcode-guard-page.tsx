import { useRef, useState } from "react";

import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage, WorkspaceSection } from "@/components/ui/workspace-layout";
import { GuardActivityList } from "@/features/transcode-guard/components/guard-activity-list";
import { GuardCleanupControls } from "@/features/transcode-guard/components/guard-cleanup-controls";
import { GuardControls } from "@/features/transcode-guard/components/guard-controls";
import { GuardOverview } from "@/features/transcode-guard/components/guard-overview";
import { GuardStreamHistory } from "@/features/transcode-guard/components/guard-stream-history";
import { guardActionForTarget, hasAuthoritativeGuardState } from "@/features/transcode-guard/guard-state";
import { useTranscodeGuard } from "@/features/transcode-guard/use-transcode-guard";
import { GuardSettingsWorkspace } from "@/features/transcode-guard-settings/components/guard-settings-workspace";
import { WriteAction } from "@/features/session/workspace-capabilities";

function TranscodeGuardPage() {
  const [hideCorrect, setHideCorrect] = useState(true);
  const confirmation = useConfirmationDialog();
  const { status, checkNow, setState, cleanupEvents, cleanupStreams } = useTranscodeGuard();
  const snapshot = status.data;
  const controlsError = checkNow.error || setState.error;
  const stateAuthorityRef = useRef({ snapshot, error: status.error });
  stateAuthorityRef.current = { snapshot, error: status.error };

  const stateReady = hasAuthoritativeGuardState(snapshot, status.error);

  async function changeGuardState(nextRunning: boolean) {
    const initialState = stateAuthorityRef.current;
    if (!hasAuthoritativeGuardState(initialState.snapshot, initialState.error)) return;
    if (
      !nextRunning &&
      !(await confirmation.confirm({
        title: "Ferma Transcode Guard",
        description:
          "Il monitor smetterà di rilevare e correggere le nuove transcodifiche finché non lo riattivi.",
        confirmLabel: "Ferma monitor",
        tone: "danger",
      }))
    )
      return;
    const currentState = stateAuthorityRef.current;
    if (!hasAuthoritativeGuardState(currentState.snapshot, currentState.error)) return;
    setState.mutate(guardActionForTarget(nextRunning));
  }

  return (
    <WorkspacePage>
      <WorkspaceSection id="transcode-guard-panel" className="transcode-guard-workspace" aria-labelledby="transcode-guard-title" tabIndex={-1}>
        <WorkspaceHeading
          className="transcode-guard-workspace-header"
          level="section"
          title="Transcode Guard"
          titleId="transcode-guard-title"
          description="Monitora gli stream e interviene sulle vere transcodifiche video."
          actions={<GuardControls
            running={snapshot?.running}
            stateReady={stateReady}
            checking={checkNow.isPending}
            changingState={setState.isPending}
            refreshing={status.isFetching}
            error={controlsError}
            onCheck={() => checkNow.mutate()}
            onStateChange={(running) => void changeGuardState(running)}
            onRefresh={() => void status.refetch()}
          />}
        />

        {status.error ? <div className="inline-alert inline-alert--error" role="alert">{status.error.message}</div> : null}
        {snapshot?.last_result.errors.length ? <div className="inline-alert inline-alert--error" role="alert">{snapshot.last_result.errors.join(" · ")}</div> : null}
        {status.isLoading ? <div className="loading-state">Caricamento stato Transcode Guard...</div> : null}

        {snapshot ? <GuardOverview running={snapshot.running} activeViolations={snapshot.active_violations.length} lastResult={snapshot.last_result} updatedAt={status.dataUpdatedAt} /> : null}
        <GuardSettingsWorkspace />

        {snapshot ? (
          <div className="guard-activity-grid">
            <GuardActivityList title="Violazioni attive" icon="alert" records={snapshot.active_violations} empty="Nessuna violazione attiva." />
            <GuardActivityList
              title="Interventi recenti"
              icon="alert"
              records={snapshot.recent_events}
              empty="Nessun intervento registrato."
              tools={<WriteAction><GuardCleanupControls label="interventi" busy={cleanupEvents.isPending} error={cleanupEvents.error} deleted={cleanupEvents.data?.deleted} onCleanup={(before) => cleanupEvents.mutate(before)} /></WriteAction>}
            />
            <GuardActivityList title="Eventi player" icon="event" records={snapshot.playback_events.rows} empty="Nessun evento player registrato." />
          </div>
        ) : null}
        {snapshot ? (
          <GuardStreamHistory
            history={snapshot.stream_history}
            hideCorrect={hideCorrect}
            onHideCorrectChange={setHideCorrect}
            tools={<WriteAction><GuardCleanupControls label="stream" busy={cleanupStreams.isPending} error={cleanupStreams.error} deleted={cleanupStreams.data?.deleted} onCleanup={(before) => cleanupStreams.mutate(before)} /></WriteAction>}
          />
        ) : null}
      </WorkspaceSection>
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { TranscodeGuardPage };
