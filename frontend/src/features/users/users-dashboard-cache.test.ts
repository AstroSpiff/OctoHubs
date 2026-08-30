import { describe, expect, it } from "vitest";

import {
  updateDashboardGroupSettings,
  updateDashboardGroupSyncStatus,
  updateDashboardLeader,
  updateDashboardUser,
} from "@/features/users/users-dashboard-cache";
import type { EmbyUser, UsersDashboard } from "@/features/users/types";

const anna = {
  server_id: "green",
  user_id: "anna",
  name: "Anna",
  enable_remote_access: true,
  enable_downloading: true,
  is_leader: true,
} as EmbyUser;
const luca = {
  server_id: "purple",
  user_id: "luca",
  name: "Luca",
  enable_remote_access: true,
  enable_downloading: true,
  is_leader: false,
} as EmbyUser;
const dashboard = {
  servers: [],
  groups: [
    {
      id: "family",
      name: "Famiglia",
      is_linked: true,
      users: [anna, luca],
      auto_sync: false,
      sync_playstate: true,
    },
  ],
} as UsersDashboard;

describe("users dashboard cache", () => {
  it("updates only the chosen user", () => {
    const next = updateDashboardUser(dashboard, anna, {
      enable_remote_access: false,
      is_remote_disabled: true,
    });

    expect(next.groups[0].users[0].enable_remote_access).toBe(false);
    expect(next.groups[0].users[1].enable_remote_access).toBe(true);
  });

  it("updates group sync settings without changing other groups", () => {
    const next = updateDashboardGroupSettings(dashboard, {
      group_id: "family",
      auto_sync: true,
      sync_type: "one_way",
      sync_resume: false,
      sync_playstate: true,
      sync_config: false,
      sync_library_access: false,
      sync_favorites: false,
      sync_playlists: false,
      config_categories: [],
      playstate_bootstrap_done: false,
      favorites_bootstrap_done: false,
      playlists_bootstrap_done: false,
    });

    expect(next.groups[0]).toMatchObject({
      auto_sync: true,
      sync_type: "one_way",
    });
  });

  it("switches the leader within the selected group only", () => {
    const next = updateDashboardLeader(dashboard, "family", luca);

    expect(next.groups[0].users.map((user) => user.is_leader)).toEqual([
      false,
      true,
    ]);
  });

  it("marks only the requested group as syncing while the background operation starts", () => {
    const next = updateDashboardGroupSyncStatus(
      dashboard,
      "family",
      "running",
      "Sincronizzazione manuale avviata",
    );

    expect(next.groups[0]).toMatchObject({
      last_sync_status: "running",
      last_sync_message: "Sincronizzazione manuale avviata",
    });
  });
});
