// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeComboCard } from "@/features/probe/components/probe-combo-card";

describe("ProbeComboCard", () => {
  it("mostra ogni contatore del workflow una sola volta nella bacheca operativa", () => {
    const markup = renderToStaticMarkup(
      <ProbeComboCard
        scope="libraries"
        serverStatuses={[]}
        actions={[]}
      />,
    );

    expect(markup.match(/Da fare/g)).toHaveLength(1);
    expect(markup.match(/In esecuzione/g)).toHaveLength(1);
    expect(markup.match(/Terminato/g)).toHaveLength(1);
    expect(markup).not.toContain("probe-worker-stats");
  });

  it("mostra un'interruzione nella colonna terminata con esito esplicito", () => {
    const task = {
      id: "stopped",
      type: "processing",
      server_id: "black",
      library_id: "series",
    };
    const markup = renderToStaticMarkup(
      <ProbeComboCard
        scope="libraries"
        serverStatuses={[{
          serverId: "black",
          serverName: "BlackPrimrose",
          libraryNames: { series: "Serie TV" },
          status: {
            running: false,
            board_reset: true,
            queue: [task],
            last_run: {
              status: "interrupted",
              tasks: [{ ...task, result: "warning", note: "Interrotto" }],
            },
          },
        }]}
        actions={[]}
      />,
    );

    expect(markup).toContain("Terminato");
    expect(markup).toContain("Interrotto");
    expect(markup).toContain("is-interrupted");
  });

  it("assegna colori semantici distinti agli esiti terminali", () => {
    const tasks = [
      { id: "ok", type: "processing", server_id: "black" },
      { id: "partial", type: "processing", server_id: "black" },
      { id: "error", type: "processing", server_id: "black" },
    ];
    const markup = renderToStaticMarkup(
      <ProbeComboCard
        scope="libraries"
        serverStatuses={[{
          serverId: "black",
          serverName: "Black",
          status: {
            board_reset: true,
            queue: tasks,
            last_run: {
              status: "error",
              tasks: [
                { ...tasks[0], result: "success", note: "Completato" },
                { ...tasks[1], result: "warning", note: "Incompleti: 2" },
                { ...tasks[2], result: "error", note: "Errore" },
              ],
            },
          },
        }]}
        actions={[]}
      />,
    );

    expect(markup).toContain("is-completed");
    expect(markup).toContain("is-partial");
    expect(markup).toContain("is-error");
  });

  it("mostra nome e progresso propri per ogni libreria", () => {
    const markup = renderToStaticMarkup(
      <ProbeComboCard
        scope="libraries"
        serverStatuses={[{
          serverId: "black",
          serverName: "BlackPrimrose",
          libraryNames: { films: "Film", series: "Serie TV" },
          processingStatus: {
            running: true,
            started_at: "2026-09-19T08:01:00Z",
            current_library_id: "films",
            current_item: "Film corrente",
            target_library_ids: ["films", "series"],
            library_queue_totals: { films: 200, series: 400 },
            library_queue_results: {
              films: { processed: 10 },
              series: { processed: 0 },
            },
          },
        }]}
        actions={[]}
      />,
    );

    expect(markup).toContain("BlackPrimrose · Film");
    expect(markup).toContain("BlackPrimrose · Serie TV");
    expect(markup).toContain("10/200 · 5%");
    expect(markup).toContain("0/400 · 0%");
    expect(markup.match(/Film corrente/g)).toHaveLength(1);
  });

  it("mostra nell'ultimo run libreria, tempi, contatori ed esito reale", () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    act(() => root.render(
      <ProbeComboCard
        scope="libraries"
        serverStatuses={[{
          serverId: "black",
          serverName: "Black",
          libraryNames: { movies: "Film" },
          status: {
            last_run: {
              started_at: "2026-09-19T07:00:00Z",
              finished_at: "2026-09-19T07:02:05Z",
              status: "error",
              tasks: [{
                type: "processing",
                server_id: "black",
                library_id: "movies",
                result: "error",
                note: "Errori: 1",
                total: 14,
                processed: 12,
                incomplete: 1,
                errors: 1,
              }],
            },
          },
        }]}
        actions={[]}
      />,
    ));
    const toggle = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("Ultimo run"));
    act(() => toggle?.dispatchEvent(new MouseEvent("click", { bubbles: true })));

    expect(container.textContent).toContain("Film");
    expect(container.textContent).toContain("Durata: 2 min 5 s");
    expect(container.textContent).toContain("12 completati su 14");
    expect(container.textContent).toContain("1 incompleto");
    expect(container.textContent).toContain("1 errore");
    expect(container.textContent).toContain("Errore");

    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });
});
