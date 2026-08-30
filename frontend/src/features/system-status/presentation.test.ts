import { describe, expect, it } from "vitest";

import {
  systemStatusHref,
  formatSystemStatusMetric,
  formatSystemStatusTime,
  systemStatusRouterTarget,
} from "@/features/system-status/presentation";
import { systemStatusOverviewHeadline } from "@/features/system-status/status-overview-presentation";

describe("systemStatusHref", () => {
  it("formats status timestamps for the Italian interface", () => {
    const formatted = formatSystemStatusTime("2026-08-11T11:30:45+00:00");

    expect(formatted).toMatch(/\d{2}\/\d{2}\/2026/);
    expect(formatted).toMatch(/\d{2}:\d{2}:\d{2}/);
    expect(formatSystemStatusTime("not-a-date")).toBe("not-a-date");
  });

  it("formats raw diagnostic timestamps but leaves ordinary metric values intact", () => {
    expect(formatSystemStatusMetric("2026-08-11T11:30:45+00:00")).toMatch(
      /\d{2}\/\d{2}\/2026.*\d{2}:\d{2}:\d{2}/,
    );
    expect(formatSystemStatusMetric("0.4.2.0")).toBe("0.4.2.0");
    expect(formatSystemStatusMetric("/storage/db-backups")).toBe(
      "/storage/db-backups",
    );
  });

  it("opens migrated Emby sections inside React", () => {
    expect(systemStatusHref("/emby#actions?focus=emby-operations")).toBe(
      "/app/emby-live?focus=emby-live-servers",
    );
    expect(systemStatusHref("/emby#live?focus=emby-live-servers")).toBe(
      "/app/emby-live?focus=emby-live-servers",
    );
    expect(
      systemStatusHref("/emby#transcode-guard?focus=transcode-guard-panel"),
    ).toBe("/app/transcode-guard?focus=transcode-guard-panel");
    expect(
      systemStatusHref(
        "/configuration#event-bridge?focus=event-bridge-configuration",
      ),
    ).toBe("/app/configuration/event-bridge?focus=event-bridge-configuration");
  });

  it("opens all migrated configuration sections in their matching tab", () => {
    expect(systemStatusHref("/configuration#services")).toBe(
      "/app/configuration/services",
    );
    expect(systemStatusHref("/configuration#emby-servers")).toBe(
      "/app/configuration/servers",
    );
    expect(systemStatusHref("/dashboard#requests?focus=requests-refresh")).toBe(
      "/app/research/requests?focus=requests-refresh",
    );
  });

  it("keeps every legacy status destination inside the React application", () => {
    const destinations = [
      ["/configuration#services", "/app/configuration/services"],
      ["/configuration#services?focus=configuration-database", "/app/configuration/services?focus=configuration-database"],
      ["/configuration#services?focus=configuration-connections", "/app/configuration/services?focus=configuration-connections"],
      ["/configuration#services?focus=configuration-metadata", "/app/configuration/services?focus=configuration-metadata"],
      ["/configuration#services?focus=configuration-catalogs", "/app/configuration/services?focus=configuration-catalogs"],
      ["/configuration#emby-servers", "/app/configuration/servers"],
      ["/configuration#event-bridge", "/app/configuration/event-bridge"],
      ["/emby#actions", "/app/emby-live"],
      ["/emby#live?focus=emby-live-servers", "/app/emby-live?focus=emby-live-servers"],
      ["/emby#transcode-guard", "/app/transcode-guard"],
      ["/dashboard#rules", "/app/research/rules"],
    ];

    destinations.forEach(([legacyHref, reactHref]) => {
      expect(systemStatusHref(legacyHref)).toBe(reactHref);
      expect(systemStatusRouterTarget(legacyHref)).toBe(
        reactHref.slice("/app".length),
      );
    });
  });

  it("keeps React links relative to BrowserRouter's /app basename", () => {
    expect(systemStatusRouterTarget("/emby#actions")).toBe("/emby-live");
    expect(systemStatusRouterTarget("/emby#live?focus=emby-live-servers")).toBe(
      "/emby-live?focus=emby-live-servers",
    );
    expect(systemStatusRouterTarget("/configuration#event-bridge")).toBe(
      "/configuration/event-bridge",
    );
    expect(systemStatusRouterTarget("/emby#actions?focus=emby-operations")).toBe(
      "/emby-live?focus=emby-live-servers",
    );
    expect(systemStatusRouterTarget("/login")).toBeNull();
  });

  it("does not present an empty status snapshot as healthy while loading", () => {
    expect(
      systemStatusOverviewHeadline(
        { ok: 0, warning: 0, error: 0, unknown: 0 },
        true,
      ),
    ).toBe("Controllo in corso");
    expect(
      systemStatusOverviewHeadline(
        { ok: 3, warning: 0, error: 0, unknown: 0 },
        false,
      ),
    ).toBe("Tutto sotto controllo");
  });
});
