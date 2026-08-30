import { describe, expect, it } from "vitest";

import { comboTasksForServers } from "@/features/probe/probe-combo-presentation";

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
});
