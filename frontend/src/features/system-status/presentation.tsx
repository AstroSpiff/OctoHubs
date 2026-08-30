import { AlertTriangle, CheckCircle2, CircleHelp, XCircle } from "@/components/ui/icons";

import type { Severity } from "@/features/system-status/types";

export function severityIcon(severity: Severity, size = 18) {
  const iconProps = { size, strokeWidth: 2, "aria-hidden": true } as const;
  if (severity === "ok") return <CheckCircle2 {...iconProps} />;
  if (severity === "warning") return <AlertTriangle {...iconProps} />;
  if (severity === "error") return <XCircle {...iconProps} />;
  return <CircleHelp {...iconProps} />;
}

export function severityLabel(severity: Severity) {
  return {
    ok: "OK",
    warning: "Avviso",
    error: "Errore",
    unknown: "Da verificare",
  }[severity];
}

export function formatSystemStatusTime(value?: string | null): string {
  if (!value) return "Mai";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

/**
 * Metrics usually contain concise labels, but a few diagnostics expose a raw
 * ISO timestamp. Keep those values consistent with the Italian UI without
 * reformatting paths, versions, or arbitrary text.
 */
export function formatSystemStatusMetric(value?: string | null): string {
  const text = value?.trim() || "N/D";
  return /^\d{4}-\d{2}-\d{2}T/.test(text)
    ? formatSystemStatusTime(text)
    : text;
}

/**
 * The health API now emits React links, but older payloads and cached snapshots
 * can still contain retired template anchors. Keep those links usable.
 */
export function systemStatusHref(href: string): string {
  const [pathAndQuery, fragment = ""] = href.split("#", 2);
  const [path] = pathAndQuery.split("?", 2);
  const target = fragment.split("?", 1)[0];
  const focus = new URLSearchParams(fragment.split("?", 2)[1] || "").get("focus") || "";

  if (path === "/configuration") {
    const routes: Record<string, string> = {
      "emby-servers": reactAppHref("/configuration/servers", focus),
      telegram: reactAppHref("/configuration/telegram", focus),
      services: reactAppHref("/configuration/services", focus),
      "event-bridge": reactAppHref("/configuration/event-bridge", focus),
      "system-status": reactAppHref("/configuration/system-status", focus),
    };
    return routes[target] || href;
  }
  if (path === "/dashboard") {
    const routes: Record<string, string> = {
      rules: reactAppHref("/research/rules", focus),
      requests: reactAppHref("/research/requests", focus),
    };
    return routes[target] || href;
  }
  if (path !== "/emby") return href;

  const routes: Record<string, string> = {
    actions: reactAppHref("/emby-live", focus === "emby-operations" ? "emby-live-servers" : focus),
    live: reactAppHref("/emby-live", focus),
    "transcode-guard": reactAppHref("/transcode-guard", focus),
    "transcode-stats": reactAppHref("/stream-stats", focus),
    libraries: reactAppHref("/libraries", focus),
    latest: reactAppHref("/latest", focus),
    users: reactAppHref("/users", focus),
  };
  return routes[target] || href;
}

function reactAppHref(path: string, focus: string): string {
  const query = focus ? `?focus=${encodeURIComponent(focus)}` : "";
  return `/app${path}${query}`;
}

/**
 * BrowserRouter already owns the /app basename. Links passed to it must stay
 * relative to that basename, otherwise React would produce /app/app/...
 */
export function systemStatusRouterTarget(href: string): string | null {
  const target = systemStatusHref(href);
  if (!target.startsWith("/app/")) return null;
  return target.slice("/app".length);
}
