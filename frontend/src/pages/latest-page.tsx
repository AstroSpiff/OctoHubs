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
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";

const emptyItems: LatestItem[] = [];

function LatestPage() {
  const latest = useEmbyLatest();
  const confirmation = useConfirmationDialog();
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
  const errors = [
    latest.snapshot.error,
    latest.configuration.error,
    latest.refresh.error,
    latest.notify.error,
    latest.workflow.error,
    latest.preview.error,
    latest.enrich.error,
    latest.clearState.error,
    latest.reset.error,
    latest.resetScanTracking.error,
  ].filter(Boolean);
  const notice =
    latest.refresh.data?.message ||
    latest.notify.data?.message ||
    latest.workflow.data?.message ||
    latest.preset.data?.message ||
    latest.removePreset.data?.message ||
    latest.rule.data?.message ||
    latest.setRuleEnabled.data?.message ||
    latest.removeRule.data?.message ||
    latest.clearState.data?.message ||
    latest.reset.data?.message ||
    latest.resetScanTracking.data?.message;

  async function removePreset(preset: LatestPreset) {
    if (!await confirmation.confirm({ title: "Rimuovi preset", description: `Rimuovere il preset “${preset.name}”?`, confirmLabel: "Rimuovi preset", tone: "danger" })) return;
    latest.removePreset.mutate(preset.id);
  }
  async function removeRule(rule: LatestRule) {
    if (!await confirmation.confirm({ title: "Elimina regola", description: `Eliminare la regola “${rule.name}”?`, confirmLabel: "Elimina regola", tone: "danger" })) return;
    latest.removeRule.mutate(rule.id);
  }
  async function confirmAction(title: string, message: string, action: () => void) {
    if (!await confirmation.confirm({ title, description: message, confirmLabel: "Conferma", tone: "danger" })) return;
    action();
  }
  function enrich(item: LatestItem) {
    return latest.enrich.mutateAsync(item).then((result) => result.item);
  }

  return (
    <WorkspacePage className="latest-workspace">
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
        onRefresh={() => latest.refresh.mutate(latest.fetchLimits)}
        onNotify={() =>
          latest.notify.mutate(
            latest.fetchLimits.perServerLimit,
          )
        }
        onWorkflow={() => latest.workflow.mutate()}
        onVerify={() => setVerifyOpen(true)}
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
      {errors.map((error, index) => (
        <div
          className="inline-alert inline-alert--error"
          role="alert"
          key={`${error?.message}-${index}`}
        >
          {error?.message}
        </div>
      ))}
      {notice ? (
        <div className="inline-alert inline-alert--success" role="status">
          {notice}
        </div>
      ) : null}
      {latest.snapshot.isLoading && !snapshot ? (
        <div className="loading-state">Caricamento pubblicazioni...</div>
      ) : null}
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
            onSave={(preset) => latest.preset.mutateAsync(preset)}
            onRemove={(preset) => void removePreset(preset)}
            onTemplateChange={updatePreviewTemplate}
            onDirtyChange={(dirty) => updateDirty("preset", dirty)}
            error={
              latest.preset.error?.message || latest.removePreset.error?.message
            }
          />
          <LatestNotificationPreview
            template={previewTemplate || activeTemplate}
            movies={previewMovies}
            series={previewSeries}
            result={latest.preview.data}
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
              error={
                latest.rule.error?.message ||
                latest.setRuleEnabled.error?.message ||
                latest.removeRule.error?.message
              }
              onSave={(rule: LatestRuleInput) => latest.rule.mutateAsync(rule)}
              onToggle={(rule) =>
                latest.setRuleEnabled.mutate({
                  ruleId: rule.id,
                  enabled: !rule.enabled,
                })
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
                  () => latest.reset.mutate(),
                )
              }
              onClearState={() =>
                void confirmAction(
                  "Azzera tracking notifiche",
                  "Azzera lo stato di tracking delle notifiche mantenendo tutte le altre configurazioni?",
                  () => latest.clearState.mutate(),
                )
              }
              onClearScans={() =>
                void confirmAction(
                  "Elimina dati scansione",
                  "Elimina i dati salvati su scansioni e refresh metadata?",
                  () => latest.resetScanTracking.mutate(),
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
        onClose={() => setVerifyOpen(false)}
        onEnrich={enrich}
      />
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { LatestPage };
