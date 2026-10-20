import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { LatestDataVerify } from "@/features/emby-latest/components/latest-data-verify";
import { LatestDisplayLimitControl } from "@/features/emby-latest/components/latest-display-limit-control";
import {
  LatestNotificationsMaintenance,
  LatestPublicationsMaintenance,
} from "@/features/emby-latest/components/latest-maintenance";
import { LatestNotificationPreview } from "@/features/emby-latest/components/latest-notification-preview";
import { LatestPresetManager } from "@/features/emby-latest/components/latest-preset-manager";
import { LatestRefreshProgress } from "@/features/emby-latest/components/latest-refresh-progress";
import { LatestReleaseColumn } from "@/features/emby-latest/components/latest-release-card";
import {
  LatestNotificationActions,
  LatestPublicationActions,
  LatestReleaseHeader,
  LatestServerSelector,
} from "@/features/emby-latest/components/latest-release-controls";
import { LatestRuleManager } from "@/features/emby-latest/components/latest-rule-manager";
import {
  LatestViewTabs,
  type LatestView,
} from "@/features/emby-latest/components/latest-view-tabs";
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
  LatestPresetInput,
  LatestRule,
  LatestRuleInput,
} from "@/features/emby-latest/types";
import { useEmbyLatest } from "@/features/emby-latest/use-emby-latest";
import { useLatestActionFeedback } from "@/features/emby-latest/use-latest-action-feedback";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";

const emptyItems: LatestItem[] = [];
const emptyPresets: LatestPreset[] = [];

function LatestPage() {
  const latest = useEmbyLatest();
  const confirmation = useConfirmationDialog();
  const actionFeedback = useLatestActionFeedback();
  const [searchParams, setSearchParams] = useSearchParams();
  const { mutate: previewLatest } = latest.preview;
  const [serverId, setServerId] = useState("all");
  const [displayLimit, setDisplayLimit] = useState(readLatestDisplayLimit);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [previewDraft, setPreviewDraft] = useState<LatestPresetInput | null>(null);
  const [drafts, setDrafts] = useState({ preset: false, rule: false });
  const [activeView, setActiveView] = useState<LatestView>(() =>
    searchParams.get("view") === "telegram" ? "telegram" : "publications",
  );
  const hasUnsavedChanges = drafts.preset || drafts.rule;
  useBeforeUnloadWarning(hasUnsavedChanges);
  useUnsavedChangesNavigationGuard(hasUnsavedChanges, confirmation.confirm);
  const snapshot = latest.snapshot.data;
  const configuration = latest.configuration.data;
  const movies = snapshot?.movies || emptyItems;
  const series = snapshot?.series || emptyItems;
  const presets = configuration?.presets || emptyPresets;
  const activePreset =
    presets.find(
      (preset) => preset.id === configuration?.settings.active_preset_id,
    ) || presets[0];
  const selectedPreset =
    presets.find((preset) => preset.id === selectedPresetId) || activePreset;
  const previewTemplate = previewDraft?.template ?? selectedPreset?.template ?? "";
  const previewSourceLabel = previewDraft
    ? `Modifiche in corso: ${previewDraft.name.trim() || "nuovo preset"}`
    : selectedPreset
      ? `Preset selezionato: ${selectedPreset.name}`
      : "Nessun preset selezionato";

  useEffect(() => {
    setSelectedPresetId((current) =>
      presets.some((preset) => preset.id === current)
        ? current
        : activePreset?.id || "",
    );
  }, [activePreset?.id, presets]);

  useEffect(() => {
    const view =
      searchParams.get("view") === "telegram" ? "telegram" : "publications";
    setActiveView((current) => (current === view ? current : view));
  }, [searchParams]);

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
  const updateDisplayLimit = useCallback((limit: number) => {
    setDisplayLimit(limit);
    saveLatestDisplayLimit(limit);
  }, []);
  const updateView = useCallback(
    (view: LatestView) => {
      setActiveView(view);
      const next = new URLSearchParams(searchParams);
      if (view === "publications") next.delete("view");
      else next.set("view", view);
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );
  const updateDirty = useCallback((scope: "preset" | "rule", dirty: boolean) => {
    setDrafts((current) => current[scope] === dirty ? current : { ...current, [scope]: dirty });
  }, []);
  const previewNotification = useCallback(
    (items: Partial<Record<"movie" | "series", LatestItem>>) =>
      previewLatest({
        template: previewTemplate,
        items,
      }),
    [previewLatest, previewTemplate],
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
      <LatestReleaseHeader
        workflowing={latest.workflow.isPending || latest.workflowActive}
      />
      {actionFeedback.notice ? (
        <div
          className={`inline-alert inline-alert--${actionFeedback.notice.tone}`}
          role={actionFeedback.notice.tone === "error" ? "alert" : "status"}
        >
          {actionFeedback.notice.message}
        </div>
      ) : null}
      <div className="latest-view-layout">
        <div className="latest-view-controls">
          <LatestViewTabs activeView={activeView} onChange={updateView} />
          <div
            className={`latest-context-toolbar latest-context-toolbar--${activeView}`}
          >
            <LatestServerSelector
              servers={configuration?.servers || []}
              selectedServer={serverId}
              onServerChange={setServerId}
            />
            <div className="latest-context-commands">
              {activeView === "publications" ? (
                <>
                  <LatestPublicationActions
                    loading={latest.snapshot.isLoading}
                    refreshing={latest.refresh.isPending || latest.isRefreshing}
                    notifying={latest.notify.isPending}
                    workflowing={latest.workflow.isPending || latest.workflowActive}
                    onRefresh={() => {
                      void actionFeedback
                        .run(
                          () => latest.refresh.mutateAsync(latest.fetchLimits),
                          "Aggiornamento pubblicazioni avviato.",
                        )
                        .catch(() => undefined);
                    }}
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
                  <div className="latest-publications-toolbar-meta">
                    {snapshot?.cached_at || latest.isRefreshing ? (
                      <p className="latest-cache-status">
                        {formatLatestAge(snapshot?.cached_at)}
                        {latest.isRefreshing ? " · aggiornamento in corso" : ""}
                      </p>
                    ) : null}
                    <LatestDisplayLimitControl
                      displayLimit={displayLimit}
                      maxMovies={configuration?.settings.limits.max_movies}
                      maxSeries={configuration?.settings.limits.max_series}
                      onLimitChange={updateDisplayLimit}
                    />
                  </div>
                </>
              ) : (
                <LatestNotificationActions
                  loading={latest.snapshot.isLoading}
                  refreshing={latest.refresh.isPending || latest.isRefreshing}
                  notifying={latest.notify.isPending}
                  workflowing={latest.workflow.isPending || latest.workflowActive}
                  onNotify={() =>
                    void actionFeedback
                      .run(
                        () => latest.notify.mutateAsync(latest.fetchLimits.perServerLimit),
                        "Invio notifiche completato.",
                      )
                      .catch(() => undefined)
                  }
                />
              )}
            </div>
          </div>
        </div>
      <section
        id="latest-view-panel-publications"
        className="latest-view-panel latest-publications-panel"
        role="tabpanel"
        aria-labelledby="latest-view-tab-publications"
        tabIndex={0}
        hidden={activeView !== "publications"}
      >
        {latest.isRefreshing ? (
          <LatestRefreshProgress progress={latest.progress.data} />
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
        <LatestPublicationsMaintenance
          resetting={latest.reset.isPending}
          onReset={() =>
            void confirmAction(
              "Ricostruisci pubblicazioni",
              "Cancella i dati salvati delle pubblicazioni e il registro degli invii. Al prossimo aggiornamento i contenuti verranno ricostruiti da Emby e quelli già inviati potrebbero tornare notificabili. Continuare?",
              "Pubblicazioni reimpostate.",
              () => latest.reset.mutateAsync(),
            )
          }
        />
      </section>
      <section
        id="latest-view-panel-telegram"
        className="latest-view-panel latest-configuration"
        role="tabpanel"
        aria-labelledby="latest-view-tab-telegram"
        tabIndex={0}
        hidden={activeView !== "telegram"}
      >
        <div className="latest-configuration-grid">
          <LatestPresetManager
            presets={presets}
            selectedPresetId={selectedPreset?.id || ""}
            saving={latest.configurationBusy}
            removingId={
              latest.removePreset.isPending
                ? latest.removePreset.variables
                : undefined
            }
            onSave={async (preset) => {
              const result = await actionFeedback.run(
                () => latest.preset.mutateAsync(preset),
                "Preset salvato.",
                "preset",
              );
              setSelectedPresetId(result.settings.active_preset_id);
              return result;
            }}
            onRemove={(preset) => void removePreset(preset)}
            onSelectPreset={setSelectedPresetId}
            onDraftChange={setPreviewDraft}
            onDirtyChange={(dirty) => updateDirty("preset", dirty)}
            error={actionFeedback.errorFor("preset")}
          />
          <LatestNotificationPreview
            template={previewTemplate}
            sourceLabel={previewSourceLabel}
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
            <LatestNotificationsMaintenance
              clearing={latest.clearState.isPending}
              onClearState={() =>
                void confirmAction(
                  "Reimposta notifiche inviate",
                  "Dimenticare quali pubblicazioni risultano già inviate? Il prossimo invio potrebbe ripeterle; preset e regole resteranno invariati.",
                  "Registro notifiche reimpostato.",
                  () => latest.clearState.mutateAsync(),
                )
              }
            />
          </div>
        </div>
      </section>
      </div>
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
