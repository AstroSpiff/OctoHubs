import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LiveServerCard } from "@/features/emby-live/components/live-server-card";

describe("LiveServerCard", () => {
  it("keeps the restart and task-stop controls beside the relevant live server", () => {
    const markup = renderToStaticMarkup(
      <LiveServerCard
        server={{
          server: {
            id: "green",
            name: "Green",
            enabled: true,
            last_action: {
              name: "Riavvio server",
              timestamp: "2026-08-17T09:00:00Z",
              result: "Completato",
            },
          },
          status: { ok: true, version: "4.8.0" },
          running_tasks: [{ id: "scan", name: "Scansione", state: "Running", progress: 40 }],
          tasks_error: null,
          streams: [],
          streams_error: null,
        }}
        controls={{
          refreshing: false,
          refreshError: "Il server Green non risponde.",
          restarting: false,
          restartDisabled: false,
          stoppingTaskKeys: new Set(),
          taskStopErrors: {},
          onRefresh: () => undefined,
          onRestart: () => undefined,
          onStopTask: () => undefined,
        }}
      />,
    );

    expect(markup).toContain("Riavvia server");
    expect(markup).toContain('aria-label="Ferma Scansione"');
    expect(markup).toContain("Il server Green non risponde.");
    expect(markup).toContain("Ultima operazione: Riavvio server");
  });
});
