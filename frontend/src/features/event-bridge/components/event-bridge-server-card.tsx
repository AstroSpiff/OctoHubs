import {
  ChevronDown,
  CircleAlert,
  Settings2,
  Wifi,
  WifiOff,
} from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EventBridgeSettingsForm } from "@/features/event-bridge/components/event-bridge-settings";
import { EventBridgeTargetList } from "@/features/event-bridge/components/event-bridge-target-list";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import {
  eventBridgeSyncSeverity,
  formatEventBridgeTime,
} from "@/features/event-bridge/presentation";
import type {
  EventBridgeServer,
  EventBridgeSettings,
} from "@/features/event-bridge/types";
import type { Severity } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function transportSeverity(className: string): Severity {
  if (className === "status-ok") return "ok";
  if (className === "status-fail") return "error";
  return "unknown";
}

function EventBridgeServerCard({
  server,
  draft,
  dirty,
  saving,
  provisioning,
  locked,
  saveError,
  provisionError,
  onChange,
  onSave,
  onProvision,
}: {
  server: EventBridgeServer;
  draft: EventBridgeSettings;
  dirty: boolean;
  saving: boolean;
  provisioning: boolean;
  locked: boolean;
  saveError: string;
  provisionError: string;
  onChange: (settings: EventBridgeSettings) => void;
  onSave: () => void;
  onProvision: () => void;
}) {
  const diagnostics = server.diagnostics;
  const transport = transportSeverity(server.transport.class_name);
  const connected = transport === "ok";

  return (
    <article className="bridge-server" aria-labelledby={`bridge-${server.id}`}>
      <header className="bridge-server-header">
        <div className="bridge-server-title">
          <span
            className={cn(
              "transport-icon",
              connected ? "transport-icon--online" : "transport-icon--offline",
            )}
          >
            {connected ? (
              <Wifi size={20} aria-hidden="true" />
            ) : (
              <WifiOff size={20} aria-hidden="true" />
            )}
          </span>
          <div>
            <h3 id={`bridge-${server.id}`}>
              <EmbyServerIcon
                icon={server.icon}
                color={server.icon_color}
                iconStyle={server.icon_style}
                size={17}
              />
              {server.name}
            </h3>
            <p>{server.id}</p>
          </div>
        </div>
        <div className="bridge-server-statuses">
          <StatusBadge severity={transport}>
            {server.transport.label || "Nessun contatto"}
          </StatusBadge>
          {server.config_ack.label ? (
            <StatusBadge
              severity={transportSeverity(server.config_ack.class_name)}
              title={server.config_ack.title}
            >
              {server.config_ack.label}
            </StatusBadge>
          ) : null}
          <StatusBadge severity={transportSeverity(server.credential.class_name)}>
            {server.credential.label}
          </StatusBadge>
          <WriteAction>
            <Button
              type="button"
              variant="secondary"
              size="compact"
              disabled={provisioning || locked}
              onClick={onProvision}
            >
              <Settings2 size={15} aria-hidden="true" />
              {provisioning ? "Collegamento..." : server.credential.configured ? "Rigenera" : "Collega"}
            </Button>
          </WriteAction>
        </div>
      </header>

      {provisionError ? <p className="bridge-error" role="alert">{provisionError}</p> : null}

      <div className="bridge-diagnostics">
        <div className="bridge-diagnostic-summary">
          <StatusBadge severity={eventBridgeSyncSeverity(diagnostics.sync_status)}>
            {diagnostics.sync_label}
          </StatusBadge>
          <span>{diagnostics.plugin_version_label}</span>
        </div>
        <dl className="bridge-facts">
          <div>
            <dt>Ultimo contatto</dt>
            <dd>{formatEventBridgeTime(diagnostics.last_seen_at)}</dd>
          </div>
          <div>
            <dt>Ultimo evento</dt>
            <dd>
              {diagnostics.last_event || "Mai"}
              {diagnostics.last_event_at ? (
                <small>
                  {formatEventBridgeTime(diagnostics.last_event_at)}
                </small>
              ) : null}
            </dd>
          </div>
          <div>
            <dt>Config inviata</dt>
            <dd>{formatEventBridgeTime(diagnostics.last_config_sent_at)}</dd>
          </div>
          <div>
            <dt>Config confermata</dt>
            <dd>{formatEventBridgeTime(diagnostics.last_config_ack_at)}</dd>
          </div>
          <div>
            <dt>Canale config</dt>
            <dd>{diagnostics.last_config_transport_label}</dd>
          </div>
          <div>
            <dt>Report plugin</dt>
            <dd>
              {formatEventBridgeTime(diagnostics.last_plugin_settings_at)}
            </dd>
          </div>
          <div>
            <dt>Destinazioni plugin</dt>
            <dd>{diagnostics.target_count_label}</dd>
          </div>
        </dl>
        <EventBridgeTargetList targets={diagnostics.plugin_targets} />
        {diagnostics.last_config_ack_error ? (
          <p className="bridge-error">{diagnostics.last_config_ack_error}</p>
        ) : null}
        {diagnostics.diffs.length ? (
          <div className="bridge-differences">
            <strong>Valori diversi</strong>
            {diagnostics.diffs.map((difference) => (
              <p key={difference.label}>
                <span>{difference.label}</span>
                <span>OctoHubs: {difference.octohubs}</span>
                <span>Plugin: {difference.plugin}</span>
              </p>
            ))}
          </div>
        ) : null}
      </div>

      {server.settings_editable ? (
        <WriteAction>
          <details className="bridge-settings">
            <summary>
              <span>
                <Settings2 size={17} aria-hidden="true" /> Impostazioni plugin
              </span>
              <ChevronDown size={18} aria-hidden="true" />
            </summary>
            <EventBridgeSettingsForm
              settings={draft}
              dirty={dirty}
              saving={saving}
              locked={locked}
              onChange={onChange}
              onSave={onSave}
            />
            {saveError ? (
              <p className="bridge-save-error" role="alert">
                {saveError}
              </p>
            ) : null}
          </details>
        </WriteAction>
      ) : (
        <div className="bridge-not-ready">
          <CircleAlert size={18} aria-hidden="true" /> Le impostazioni
          compariranno dopo il primo contatto del plugin.
        </div>
      )}
    </article>
  );
}

export { EventBridgeServerCard };
