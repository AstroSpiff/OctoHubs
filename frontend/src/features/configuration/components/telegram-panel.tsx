import { Send } from "@/components/ui/icons";
import { useCallback, useEffect, useState } from "react";

import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { TelegramBotResourcePanel, TelegramChatResourcePanel } from "@/features/configuration/components/telegram-resource-panel";
import { TelegramPresetPanel } from "@/features/configuration/components/telegram-preset-panel";
import type { TelegramAction, TelegramSettingsPayload } from "@/features/configuration/types";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";

type TelegramDraftScope = "presets" | "bots" | "channels" | "groups";

function TelegramPanel({ settings, busy, notice, actionError, loadError, retrying, onAction, onDirtyChange, onRetry }: { settings?: TelegramSettingsPayload; busy: boolean; notice: string; actionError: string; loadError?: Error | null; retrying: boolean; onAction: (action: TelegramAction) => Promise<unknown>; onDirtyChange?: (dirty: boolean) => void; onRetry: () => void }) {
  const [dirtyForms, setDirtyForms] = useState<Record<TelegramDraftScope, boolean>>({ presets: false, bots: false, channels: false, groups: false });
  const updateDirty = useCallback((scope: TelegramDraftScope, dirty: boolean) => {
    setDirtyForms((current) => current[scope] === dirty ? current : { ...current, [scope]: dirty });
  }, []);
  const dirty = Object.values(dirtyForms).some(Boolean);

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  return <QueryStateBoundary error={loadError} hasData={Boolean(settings)} loadingLabel="Caricamento configurazione Telegram..." retrying={retrying} onRetry={onRetry}>
    {settings ? <section id="configuration-telegram" className="configuration-panel" aria-labelledby="configuration-telegram-title" tabIndex={-1}>
    <WorkspaceHeading level="section" context="Notifiche" leading={<Send size={18} aria-hidden="true" />} titleId="configuration-telegram-title" title="Telegram" description="Bot, gruppi, canali e preconfigurazioni per le notifiche dell'applicazione." />
    {!settings.ready ? <div className="inline-alert inline-alert--error" role="alert">Per usare Telegram serve una connessione database attiva.</div> : null}
    {notice ? <div className="inline-alert inline-alert--success" role="status">{notice}</div> : null}
    {actionError ? <div className="inline-alert inline-alert--error" role="alert">{actionError}</div> : null}
    {busy ? <div className="inline-alert inline-alert--warning" role="status">Operazione Telegram in corso...</div> : null}
    <TelegramPresetPanel presets={settings.presets} bots={settings.bots} groups={settings.groups} channels={settings.channels} busy={busy || !settings.ready} onAction={onAction} onDirtyChange={(value) => updateDirty("presets", value)} />
    <section className="telegram-resources"><header><h3>Gestione risorse</h3><p>Le risorse salvate possono essere riutilizzate in piu preconfigurazioni.</p></header><div><TelegramBotResourcePanel bots={settings.bots} busy={busy || !settings.ready} onAction={onAction} onDirtyChange={(value) => updateDirty("bots", value)} /><TelegramChatResourcePanel kind="channel" entries={settings.channels} busy={busy || !settings.ready} onAction={onAction} onDirtyChange={(value) => updateDirty("channels", value)} /><TelegramChatResourcePanel kind="group" entries={settings.groups} busy={busy || !settings.ready} onAction={onAction} onDirtyChange={(value) => updateDirty("groups", value)} /></div></section>
  </section> : null}
  </QueryStateBoundary>;
}

export { TelegramPanel };
