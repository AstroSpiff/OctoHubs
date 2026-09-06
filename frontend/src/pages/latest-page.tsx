import { useCallback, useEffect, useMemo, useState } from "react";

import { LatestDataVerify } from "@/features/emby-latest/components/latest-data-verify";
import { LatestMaintenance } from "@/features/emby-latest/components/latest-maintenance";
import { LatestNotificationPreview } from "@/features/emby-latest/components/latest-notification-preview";
import { LatestPresetManager } from "@/features/emby-latest/components/latest-preset-manager";
import { LatestRefreshProgress } from "@/features/emby-latest/components/latest-refresh-progress";
import { LatestReleaseColumn } from "@/features/emby-latest/components/latest-release-card";
import { LatestReleaseControls } from "@/features/emby-latest/components/latest-release-controls";
import { LatestRuleManager } from "@/features/emby-latest/components/latest-rule-manager";
import {
  readLatestDisplayLimit,
  saveLatestDisplayLimit,
} from "@/features/emby-latest/latest-display-preferences";
import {
  formatLatestAge,
  latestItemsForServer,
  visibleLatestItems,
} from "@/features/emby-latest/presentation";
import type {
  LatestItem,
  LatestPreset,
  LatestRule,
  LatestRuleInput,
} from "@/features/emby-latest/types";
import { useEmbyLatest } from "@/features/emby-latest/use-emby-latest";
import { useLatestActionFeedback } from "@/features/emby-latest/use-latest-action-feedback";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";

const emptyItems: LatestItem[] = [];

function LatestPage() {
  const latest = useEmbyLatest();
  const confirmation = useConfirmationDialog();
  const actionFeedback = useLatestActionFeedback();
  const { mutate: previewLatest } = latest.preview;
  const [serverId, setServerId] = useState("all");
  const [displayLimit, setDisplayLimit] = useState(readLatestDisplayLimit);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [previewTemplate, setPreviewTemplate] = useState("");
  const [drafts, setDrafts] = useState({ preset: false, rule: false });
  const hasUnsavedChanges = drafts.preset || drafts.rule;
  useBeforeUnloadWarning(hasUnsavedChanges);
  useUnsavedChangesNavigationGuard(hasUnsavedChanges, confirmation.confirm);
  const snapshot = latest.snapshot.data;
  const configuration = latest.configuration.data;
  const movies = snapshot?.movies || emptyItems;
  const series = snapshot?.series || emptyItems;
  const activeTemplate =
    configuration?.presets.find(
      (preset) => preset.id === configuration.settings.active_preset_id,
    )?.template ||
    configuration?.presets[0]?.template ||
    "";

  useEffect(() => {
    if (!previewTemplate && activeTemplate) setPreviewTemplate(activeTemplate);
  }, [activeTemplate, previewTemplate]);

  const movieItems = useMemo(
    () => visibleLatestItems(movies, serverId, displayLimit),
    [movies, serverId, displayLimit],
  );
  const seriesItems = useMemo(
    () => visibleLatestItems(series, serverId, displayLimit),
    [series, serverId, displayLimit],
  );
  const previewMovies = useMemo(
    () => latestItemsForServer(movies, serverId),
    [movies, serverId],
  );
  const previewSeries = useMemo(
    () => latestItemsForServer(series, serverId),
    [series, serverId],
  );
  const updatePreviewTemplate = useCallback(
    (template: string) => setPreviewTemplate(template || activeTemplate),
    [activeTemplate],
  );
  const updateDisplayLimit = useCallback((limit: number) => {
    setDisplayLimit(limit);
    saveLatestDisplayLimit(limit);
  }, []);
  const updateDirty = useCallback((scope: "preset" | "rule", dirty: boolean) => {
    setDrafts((current) => current[scope] === dirty ? current : { ...current, [scope]: dirty });
  }, []);
  const previewNotification = useCallback(
    (items: Partial<Record<"movie" | "series", LatestItem>>) =>
      previewLatest({
        template: previewTemplate || activeTemplate,
        items,
      }),
    [activeTemplate, previewLatest, previewTemplate],
  );
  async function removePreset(preset: LatestPreset) {
    if (!await confirmation.confirm({ title: "Rimuovi preset", description: `Rimuovere il preset “${preset.name}”?`, confirmLabel: "Rimuovi preset", tone: "danger" })) return;
    void actionFeedback
      .run(
        () => latest.removePreset.mutateAsync(preset.id),
        "Preset rimosso.",
        "preset",
      )
      .catch(() => undefined);
  }
  async function removeRule(rule: LatestRule) {
    if (!await confirmation.confirm({ title: "Elimina regola", description: `Eliminare la regola “${rule.name}”?`, confirmLabel: "Elimina regola", tone: "danger" })) return;
    void actionFeedback
      .run(
        () => latest.removeRule.mutateAsync(rule.id),
        "Regola eliminata.",
        "rule",
      )
      .catch(() => undefined);
  }
  async function confirmAction(
    title: string,
    message: string,
    successMessage: string,
    action: () => Promise<unknown>,
  ) {
    if (!await confirmation.confirm({ title, description: message, confirmLabel: "Conferma", tone: "danger" })) return;
    void actionFeedback.run(action, successMessage).catch(() => undefined);
  }
  function enrich(item: LatestItem) {
    return latest.enrich.mutateAsync(item).then((result) => result.item);
  }

  return (
    <WorkspacePage className="latest-workspace">
      <QueryStateBoundary
        error={latest.configuration.error}
        hasData={Boolean(configuration)}
        loadingLabel="Caricamento configurazione pubblicazioni..."
        retrying={latest.configuration.isFetching}
        onRetry={() => void latest.configuration.refetch()}
      >
      <LatestReleaseControls
        servers={configuration?.servers || []}
        selectedServer={serverId}
        displayLimit={displayLimit}
        maxMovies={configuration?.settings.limits.max_movies}
        maxSeries={configuration?.settings.limits.max_series}
        loading={latest.snapshot.isLoading}
        refreshing={latest.refresh.isPending || latest.isRefreshing}
        notifying={latest.notify.isPending}
        workflowing={latest.workflow.isPending || latest.workflowActive}
        onServerChange={setServerId}
        onLimitChange={updateDisplayLimit}
        onRefresh={() => {
          void actionFeedback
            .run(
              () => latest.refresh.mutateAsync(latest.fetchLimits),
              "Aggiornamento pubblicazioni avviato.",
            )
            .catch(() => undefined);
        }}
        onNotify={() =>
          void actionFeedback
            .run(
              () => latest.notify.mutateAsync(latest.fetchLimits.perServerLimit),
              "Invio notifiche completato.",
            )
            .catch(() => undefined)
        }
        onWorkflow={() => {
          void actionFeedback
            .run(() => latest.workflow.mutateAsync(), "Workflow avviato.")
            .catch(() => undefined);
        }}
        onVerify={() => {
          latest.enrich.reset();
          setVerifyOpen(true);
        }}
      />
      {snapshot?.cached_at || latest.isRefreshing ? (
        <p className="latest-cache-status">
          {formatLatestAge(snapshot?.cached_at)}
          {latest.isRefreshing ? " · aggiornamento in corso" : ""}
        </p>
      ) : null}
      {latest.isRefreshing ? (
        <LatestRefreshProgress progress={latest.progress.data} />
      ) : null}
      {actionFeedback.notice ? (
        <div
          className={`inline-alert inline-alert--${actionFeedback.notice.tone}`}
          role={actionFeedback.notice.tone === "error" ? "alert" : "status"}
        >
          {actionFeedback.notice.message}
        </div>
      ) : null}
      <QueryStateBoundary
        error={latest.snapshot.error}
        hasData={Boolean(snapshot)}
        loadingLabel="Caricamento pubblicazioni..."
        retrying={latest.snapshot.isFetching}
        onRetry={() => void latest.snapshot.refetch()}
      >
      <div className="latest-release-grid">
        <LatestReleaseColumn
          title="Film"
          items={movieItems}
          total={
            serverId === "all"
              ? movies.length
              : movies.filter((item) => item.server_id === serverId).length
          }
          emptyText={
            latest.isRefreshing
              ? "Aggiornamento Pubblicazioni in corso..."
              : "Nessun film trovato"
          }
        />
        <LatestReleaseColumn
          title="Serie TV"
          items={seriesItems}
          total={
            serverId === "all"
              ? series.length
              : series.filter((item) => item.server_id === serverId).length
          }
          emptyText={
            latest.isRefreshing
              ? "Aggiornamento Pubblicazioni in corso..."
              : "Nessuna serie trovata"
          }
        />
      </div>
      </QueryStateBoundary>
      <section className="latest-configuration">
        <WorkspaceHeading
          level="subsection"
          context="Invio automatico"
          title="Notifiche Telegram"
          description="Configura preset messaggi e regole di notifica per le pubblicazioni recenti."
        />
        <div className="latest-configuration-grid">
          <LatestPresetManager
            presets={configuration?.presets || []}
            saving={latest.configurationBusy}
            removingId={
              latest.removePreset.isPending
                ? latest.removePreset.variables
                : undefined
            }
            onSave={(preset) =>
              actionFeedback.run(
                () => latest.preset.mutateAsync(preset),
                "Preset salvato.",
                "preset",
              )
            }
            onRemove={(preset) => void removePreset(preset)}
            onTemplateChange={updatePreviewTemplate}
            onDirtyChange={(dirty) => updateDirty("preset", dirty)}
            error={actionFeedback.errorFor("preset")}
          />
          <LatestNotificationPreview
            template={previewTemplate || activeTemplate}
            movies={previewMovies}
            series={previewSeries}
            result={latest.preview.data}
            request={latest.preview.variables}
            error={latest.preview.error?.message}
            loading={latest.preview.isPending}
            onPreview={previewNotification}
          />
          <div className="latest-configuration-side">
            <LatestRuleManager
              rules={configuration?.rules || []}
              servers={configuration?.servers || []}
              presets={configuration?.presets || []}
              telegramPresets={configuration?.telegram_presets || []}
              saving={latest.configurationBusy}
              changingId={
                latest.setRuleEnabled.isPending
                  ? latest.setRuleEnabled.variables?.ruleId
                  : undefined
              }
              removingId={
                latest.removeRule.isPending
                  ? latest.removeRule.variables
                  : undefined
              }
              error={actionFeedback.errorFor("rule")}
              onSave={(rule: LatestRuleInput) =>
                actionFeedback.run(
                  () => latest.rule.mutateAsync(rule),
                  "Regola salvata.",
                  "rule",
                )
              }
              onToggle={(rule) =>
                void actionFeedback
                  .run(
                    () => latest.setRuleEnabled.mutateAsync({
                      ruleId: rule.id,
                      enabled: !rule.enabled,
                    }),
                    "Regola aggiornata.",
                    "rule",
                  )
                  .catch(() => undefined)
              }
              onRemove={(rule) => void removeRule(rule)}
              onDirtyChange={(dirty) => updateDirty("rule", dirty)}
            />
            <LatestMaintenance
              resetting={latest.reset.isPending}
              clearing={latest.clearState.isPending}
              clearingScans={latest.resetScanTracking.isPending}
              onReset={() =>
                void confirmAction(
                  "Reimposta pubblicazioni",
                  "Questa operazione azzera STATE + CACHE delle pubblicazioni. I contenuti verranno ricalcolati al prossimo aggiornamento. Continuare?",
                  "Pubblicazioni reimpostate.",
                  () => latest.reset.mutateAsync(),
                )
              }
              onClearState={() =>
                void confirmAction(
                  "Azzera tracking notifiche",
                  "Azzera lo stato di tracking delle notifiche mantenendo tutte le altre configurazioni?",
                  "Tracking notifiche azzerato.",
                  () => latest.clearState.mutateAsync(),
                )
              }
              onClearScans={() =>
                void confirmAction(
                  "Elimina dati scansione",
                  "Elimina i dati salvati su scansioni e refresh metadata?",
                  "Dati scansione eliminati.",
                  () => latest.resetScanTracking.mutateAsync(),
                )
              }
            />
          </div>
        </div>
      </section>
      <LatestDataVerify
        open={verifyOpen}
        servers={configuration?.servers || []}
        movies={movies}
        series={series}
        enriching={latest.enrich.isPending}
        error={latest.enrich.error?.message}
        onClose={() => {
          latest.enrich.reset();
          setVerifyOpen(false);
        }}
        onEnrich={enrich}
        onResetError={latest.enrich.reset}
      />
      </QueryStateBoundary>
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { LatestPage };
