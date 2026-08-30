import { CheckCircle2, CircleAlert, CircleX } from "@/components/ui/icons";

import { StatusBadge, type Severity } from "@/components/ui/badge";
import type { EmbyActionResult } from "@/features/emby-live/server-actions-api";

function LiveActionResult({ result }: { result: EmbyActionResult }) {
  const presentation = actionPresentation(result);
  const Icon = presentation.severity === "ok"
    ? CheckCircle2
    : presentation.severity === "warning"
      ? CircleAlert
      : CircleX;
  const multipleServers = result.results.length > 1;

  return (
    <section
      className={`emby-live-action-result emby-live-action-result--${presentation.severity}`}
      role={presentation.severity === "error" ? "alert" : "status"}
      aria-live="polite"
    >
      <div className="emby-live-action-result-summary">
        <Icon size={18} aria-hidden="true" />
        <div>
          <strong>{result.message}</strong>
          {multipleServers ? <span>Esito per ogni server coinvolto.</span> : null}
        </div>
        <StatusBadge severity={presentation.severity}>{presentation.label}</StatusBadge>
      </div>
      {multipleServers ? (
        <ul className="emby-live-action-result-list">
          {result.results.map((server) => (
            <li key={server.server_id} className={server.success ? "is-success" : "is-error"}>
              <strong>{server.server_name || server.server_id}</strong>
              <span>{server.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function actionPresentation(result: EmbyActionResult): { label: string; severity: Severity } {
  if (result.success) return { label: "Completato", severity: "ok" };
  if (result.partial) return { label: "Parzialmente completato", severity: "warning" };
  return { label: "Non completato", severity: "error" };
}

export { LiveActionResult };
