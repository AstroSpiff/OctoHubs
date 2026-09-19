import { describe, expect, it } from "vitest";

import {
  comboTasksForServers,
  comboTaskState,
  statusForComboTask,
} from "@/features/probe/probe-combo-presentation";

describe("comboTasksForServers", () => {
  const servers = [
    { serverId: "green", serverName: "Green" },
    { serverId: "purple", serverName: "Purple" },
  ];

  it("mostra la coda di attesa per gli ultimi aggiunti prima del primo aggiornamento", () => {
    expect(comboTasksForServers("recent", servers)).toEqual([
      expect.objectContaining({ id: "recent:discovery:green", type: "discovery" }),
      expect.objectContaining({ id: "recent:processing:green", type: "processing" }),
      expect.objectContaining({ id: "recent:discovery:purple", type: "discovery" }),
      expect.objectContaining({ id: "recent:processing:purple", type: "processing" }),
    ]);
  });

  it("preferisce e deduplica la coda pubblicata dal worker", () => {
    const tasks = comboTasksForServers("recent", [
      {
        ...servers[0],
        status: { queue: [{ id: "task-1", type: "discovery" }] },
      },
      {
        ...servers[1],
        status: { queue: [{ id: "task-1", type: "discovery" }] },
      },
    ]);

    expect(tasks).toEqual([{ id: "task-1", type: "discovery" }]);
  });

  it("non inventa una coda per il workflow librerie", () => {
    expect(comboTasksForServers("libraries", servers)).toEqual([]);
  });

  it("segue discovery e processing recenti avviati separatamente", () => {
    const tasks = comboTasksForServers("recent", [
      {
        serverId: "green",
        serverName: "Green",
        discoveryStatus: {
          running: false,
          started_at: "2026-09-19T08:00:00Z",
          last_log: "Discovery completata",
        },
        processingStatus: {
          running: true,
          started_at: "2026-09-19T08:01:00Z",
          processed: 4,
          total: 10,
        },
      },
    ]);
    const discovery = tasks.find((task) => task.type === "discovery")!;
    const processing = tasks.find((task) => task.type === "processing")!;

    expect(comboTaskState(discovery, [{
      serverId: "green",
      serverName: "Green",
      discoveryStatus: {
        running: false,
        started_at: "2026-09-19T08:00:00Z",
      },
      processingStatus: { running: true, processed: 4, total: 10 },
    }])).toBe("done");
    expect(comboTaskState(processing, [{
      serverId: "green",
      serverName: "Green",
      discoveryStatus: { running: false, started_at: "2026-09-19T08:00:00Z" },
      processingStatus: { running: true, processed: 4, total: 10 },
    }])).toBe("running");
  });

  it("segue la libreria corrente e quelle già completate", () => {
    const statuses = [{
      serverId: "black",
      serverName: "Black",
      status: {
        running: false,
        board_mode: "discovery",
        queue: [
          { id: "a", type: "discovery", server_id: "black", library_id: "lib-a" },
          { id: "b", type: "discovery", server_id: "black", library_id: "lib-b" },
          { id: "c", type: "discovery", server_id: "black", library_id: "lib-c" },
        ],
      },
      discoveryStatus: {
        running: true,
        current_library_id: "lib-b",
        completed_library_ids: ["lib-a"],
      },
    }];
    const [completed, running, pending] = comboTasksForServers(
      "libraries",
      statuses,
    );

    expect(comboTaskState(completed, statuses)).toBe("done");
    expect(comboTaskState(running, statuses)).toBe("running");
    expect(comboTaskState(pending, statuses)).toBe("todo");
  });

  it("mantiene entrambe le fasi quando discovery e processing librerie convivono", () => {
    const statuses = [{
      serverId: "black",
      serverName: "Black",
      status: {
        running: false,
        board_mode: "processing",
        queue: [{
          id: "libraries:processing:black:lib-a",
          type: "processing",
          server_id: "black",
          library_id: "lib-a",
          library_name: "Film",
        }],
      },
      discoveryStatus: {
        running: true,
        started_at: "2026-09-19T08:00:00Z",
        target_library_ids: ["lib-a"],
        current_library_id: "lib-a",
      },
      processingStatus: {
        running: true,
        started_at: "2026-09-19T08:01:00Z",
        target_library_ids: ["lib-a"],
        current_library_id: "lib-a",
      },
    }];
    const tasks = comboTasksForServers("libraries", statuses);

    expect(tasks).toHaveLength(2);
    expect(tasks.map((task) => task.type)).toEqual([
      "processing",
      "discovery",
    ]);
    expect(tasks.every((task) => task.library_name === "Film")).toBe(true);
    expect(tasks.map((task) => comboTaskState(task, statuses))).toEqual([
      "running",
      "running",
    ]);
  });

  it("porta a completato tutte le attività al termine del workflow", () => {
    const task = {
      id: "done",
      type: "processing",
      server_id: "green",
    };
    const statuses = [{
      serverId: "green",
      serverName: "Green",
      status: { running: false, board_reset: true, queue: [task] },
    }];

    expect(comboTaskState(task, statuses)).toBe("done");
  });

  it("usa lo stato della fase per progresso e dettaglio del task", () => {
    const processingStatus = {
      running: true,
      processed: 7,
      total: 12,
      current_item: "Film corrente",
    };
    const task = { type: "processing", server_id: "purple" };

    expect(statusForComboTask(task, [{
      serverId: "purple",
      serverName: "Purple",
      status: { running: true, phase: "processing" },
      processingStatus,
    }])).toBe(processingStatus);
  });
});
