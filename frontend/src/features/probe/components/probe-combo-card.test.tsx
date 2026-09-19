// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeComboCard } from "@/features/probe/components/probe-combo-card";
import { LibraryProbeControls } from "@/features/probe/components/library-probe-controls";
import { RecentProbeControls } from "@/features/probe/components/recent-probe-controls";
import { ProbeTaskBoard } from "@/features/probe/components/probe-task-board";

const noop = () => undefined;

describe("ProbeComboCard", () => {
  it("resta separata dalla bacheca e dall'ultimo run condivisi", () => {
    const markup = renderToStaticMarkup(
      <ProbeComboCard
        scope="libraries"
        actions={[]}
      />,
    );

    expect(markup).toContain("Individuazione + analisi");
    expect(markup).not.toContain("probe-task-board-panel");
    expect(markup).not.toContain("Ultimo run");
  });
});

describe("ProbeTaskBoard", () => {
  it("mostra un'interruzione nella colonna terminata con esito esplicito", () => {
    const task = {
      id: "stopped",
      type: "processing",
      server_id: "black",
      library_id: "series",
    };
    const markup = renderToStaticMarkup(
      <ProbeTaskBoard
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
      <ProbeTaskBoard
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
      />,
    );

    expect(markup).toContain("is-completed");
    expect(markup).toContain("is-partial");
    expect(markup).toContain("is-error");
  });

  it("mostra nome e progresso propri per ogni libreria", () => {
    const markup = renderToStaticMarkup(
      <ProbeTaskBoard
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
      <ProbeTaskBoard
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

describe("Probe controls hierarchy", () => {
  it("mette lo stato attività prima del workflow completo nei recenti", () => {
    const markup = renderToStaticMarkup(
      <RecentProbeControls
        allServersSelected
        serverCount={2}
        comboServerStatuses={[]}
        disabled={false}
        onRunCombo={noop}
        onStopCombo={noop}
        onRunDiscovery={noop}
        onStopDiscovery={noop}
        onRunProcessing={noop}
        onStopProcessing={noop}
      />,
    );

    expect(markup.indexOf("Stato attività")).toBeLessThan(
      markup.indexOf("Individuazione + analisi"),
    );
  });

  it("mette lo stato attività prima del workflow completo nelle librerie", () => {
    const markup = renderToStaticMarkup(
      <LibraryProbeControls
        libraries={[]}
        discoverySelected={[]}
        processingSelected={[]}
        comboServerStatuses={[]}
        disabled={false}
        onDiscoverySelectionChange={noop}
        onProcessingSelectionChange={noop}
        onRunCombo={noop}
        onStopCombo={noop}
        onRunDiscovery={noop}
        onStopDiscovery={noop}
        onRunProcessing={noop}
        onStopProcessing={noop}
      />,
    );

    expect(markup.indexOf("Stato attività")).toBeLessThan(
      markup.indexOf("Individuazione + analisi"),
    );
  });
});
