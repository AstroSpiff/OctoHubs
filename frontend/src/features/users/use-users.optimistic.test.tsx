// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getUsersDashboard,
  saveGroupSyncSettings,
  setGroupLeader,
  syncUserGroup,
} from "@/features/users/api";
import type {
  EmbyUser,
  SaveGroupSyncSettingsInput,
  UsersDashboard,
} from "@/features/users/types";
import { useUsers } from "@/features/users/use-users";

vi.mock("@/features/users/api", () => ({
  applySettingsToUsers: vi.fn(),
  cloneUsers: vi.fn(),
  createUsers: vi.fn(),
  deleteGroupUsers: vi.fn(),
  deleteUser: vi.fn(),
  getUsersDashboard: vi.fn(),
  linkUsers: vi.fn(),
  renameGroup: vi.fn(),
  renameUser: vi.fn(),
  saveGroupSyncSettings: vi.fn(),
  savePassword: vi.fn(),
  setGroupLeader: vi.fn(),
  syncUserGroup: vi.fn(),
  toggleDownloadAccess: vi.fn(),
  toggleRemoteAccess: vi.fn(),
  unlinkUser: vi.fn(),
}));

vi.mock("@/features/users/use-users-realtime", () => ({
  useUsersRealtime: vi.fn(),
}));

const anna = {
  server_id: "green",
  server_name: "Green",
  user_id: "anna",
  name: "Anna",
  is_disabled: false,
  is_user_disabled: false,
  is_remote_disabled: false,
  enable_remote_access: true,
  is_admin: false,
  is_leader: true,
} as EmbyUser;
const luca = {
  ...anna,
  server_id: "purple",
  server_name: "Purple",
  user_id: "luca",
  name: "Luca",
  is_leader: false,
} as EmbyUser;
const initialDashboard = {
  servers: [],
  groups: [{
    id: "family",
    name: "Famiglia",
    is_linked: true,
    users: [anna, luca],
    auto_sync: false,
    sync_type: "one_way",
    sync_resume: true,
    sync_playstate: true,
    sync_config: false,
    sync_library_access: false,
    sync_favorites: false,
    sync_playlists: false,
    config_categories: [],
    playstate_bootstrap_done: false,
    favorites_bootstrap_done: false,
    playlists_bootstrap_done: false,
    last_sync_status: "idle",
    last_sync_message: "Pronto",
  }],
} as UsersDashboard;
const enabledSettings: SaveGroupSyncSettingsInput = {
  group_id: "family",
  auto_sync: true,
  sync_type: "one_way",
  sync_resume: true,
  sync_playstate: true,
  sync_config: false,
  sync_library_access: false,
  sync_favorites: false,
  sync_playlists: false,
  config_categories: [],
  playstate_bootstrap_done: false,
  favorites_bootstrap_done: false,
  playlists_bootstrap_done: false,
};

let latest: ReturnType<typeof useUsers> | undefined;

function Harness() {
  latest = useUsers();
  return null;
}

describe("useUsers optimistic rollback", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.mocked(getUsersDashboard).mockRejectedValue(new Error("refetch unavailable"));
    client = new QueryClient({
      defaultOptions: {
        mutations: { retry: false },
        queries: { retry: false, staleTime: Number.POSITIVE_INFINITY },
      },
    });
    client.setQueryData(["users-dashboard"], structuredClone(initialDashboard));
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    client.clear();
    container.remove();
    latest = undefined;
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  function cachedGroup() {
    return client.getQueryData<UsersDashboard>(["users-dashboard"])?.groups[0];
  }

  it("rolls back sync status when mutation and reconciliation both fail", async () => {
    vi.mocked(syncUserGroup).mockRejectedValue(new Error("sync failed"));

    await act(async () => {
      await latest?.groupSync.mutateAsync("family").catch(() => undefined);
    });

    expect(cachedGroup()).toMatchObject({
      last_sync_status: "idle",
      last_sync_message: "Pronto",
    });
  });

  it("rolls back only the submitted group settings", async () => {
    vi.mocked(saveGroupSyncSettings).mockRejectedValue(new Error("save failed"));

    await act(async () => {
      await latest?.groupSettings.mutateAsync(enabledSettings).catch(() => undefined);
    });

    expect(cachedGroup()?.auto_sync).toBe(false);
    expect(cachedGroup()?.last_sync_message).toBe("Pronto");
  });

  it("rolls back the selected leader", async () => {
    vi.mocked(setGroupLeader).mockRejectedValue(new Error("leader failed"));

    await act(async () => {
      await latest?.leader.mutateAsync({
        group: initialDashboard.groups[0],
        user: luca,
      }).catch(() => undefined);
    });

    expect(cachedGroup()?.users.map((user) => user.is_leader)).toEqual([true, false]);
  });

  it("does not let an older failure overwrite a newer leader intent", async () => {
    let rejectFirst!: (reason: unknown) => void;
    const first = new Promise<never>((_resolve, reject) => { rejectFirst = reject; });
    vi.mocked(setGroupLeader)
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce({ ok: true });

    let firstMutation!: Promise<unknown>;
    let secondMutation!: Promise<unknown>;
    await act(async () => {
      firstMutation = latest!.leader.mutateAsync({
        group: initialDashboard.groups[0],
        user: luca,
      });
      await Promise.resolve();
      secondMutation = latest!.leader.mutateAsync({
        group: initialDashboard.groups[0],
        user: anna,
      });
      await Promise.resolve();
    });
    await act(async () => {
      rejectFirst(new Error("older request failed"));
      await firstMutation.catch(() => undefined);
      await secondMutation;
    });

    expect(cachedGroup()?.users.map((user) => user.is_leader)).toEqual([true, false]);
  });

  it("restores the confirmed base when overlapping leader intents both fail", async () => {
    let rejectFirst!: (reason: unknown) => void;
    let rejectSecond!: (reason: unknown) => void;
    const first = new Promise<never>((_resolve, reject) => { rejectFirst = reject; });
    const second = new Promise<never>((_resolve, reject) => { rejectSecond = reject; });
    vi.mocked(setGroupLeader)
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(second);

    let firstMutation!: Promise<unknown>;
    let secondMutation!: Promise<unknown>;
    await act(async () => {
      firstMutation = latest!.leader.mutateAsync({
        group: initialDashboard.groups[0],
        user: luca,
      });
      await Promise.resolve();
      secondMutation = latest!.leader.mutateAsync({
        group: initialDashboard.groups[0],
        user: anna,
      });
      await Promise.resolve();
    });
    await act(async () => {
      rejectSecond(new Error("newer request failed"));
      await secondMutation.catch(() => undefined);
      rejectFirst(new Error("older request failed"));
      await firstMutation.catch(() => undefined);
    });

    expect(cachedGroup()?.users.map((user) => user.is_leader)).toEqual([true, false]);
  });
});
