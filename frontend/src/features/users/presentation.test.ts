import { describe, expect, it } from "vitest";

import { accessPresentation, clearVisibleUserSelection, isLeaderOrStandalone, passwordPresentation, replaceVisibleUserSelection, settingsPresentation, syncPresentation, userSelectionKey, visibleUserGroups } from "@/features/users/presentation";
import type { EmbyUserGroup, UsersFilters } from "@/features/users/types";

const filters: UsersFilters = { search: "", groupType: "all", serverIds: [], statuses: [], iconProfileIds: [], sort: "name_asc_server_asc" };
const user = { server_id: "green", server_name: "Green", user_id: "u1", name: "Roy", is_disabled: false, is_user_disabled: false, is_remote_disabled: false, enable_remote_access: true, is_admin: false, is_leader: false };

describe("users presentation", () => {
  it("keeps unlinked users available to the leader selection", () => {
    expect(isLeaderOrStandalone({ id: "single", name: "Roy", users: [user], is_linked: false }, user)).toBe(true);
  });

  it("changes only the visible selection through the quick actions", () => {
    const hiddenUser = { ...user, server_id: "purple", user_id: "hidden", name: "Nascosto" };
    const visibleOtherUser = { ...user, user_id: "u2", name: "Marta" };
    const selected = new Set([userSelectionKey(hiddenUser), userSelectionKey(visibleOtherUser)]);

    expect([...replaceVisibleUserSelection(selected, [user, visibleOtherUser], [user])]).toEqual([userSelectionKey(hiddenUser), userSelectionKey(user)]);
    expect([...clearVisibleUserSelection(selected, [user, visibleOtherUser])]).toEqual([userSelectionKey(hiddenUser)]);
  });

  it("filters members without hiding a matching group", () => {
    const groups: EmbyUserGroup[] = [{ id: "linked", name: "Condiviso", is_linked: true, users: [user, { ...user, user_id: "u2", name: "Marta" }] }];
    expect(visibleUserGroups(groups, { ...filters, search: "marta" })[0].users).toHaveLength(1);
  });

  it("distinguishes a disabled account from a remote-access restriction", () => {
    expect(accessPresentation({ ...user, is_user_disabled: true }).severity).toBe("error");
    expect(accessPresentation({ ...user, is_remote_disabled: true }).severity).toBe("warning");
  });

  it("preserves the stored-password and settings alignment states", () => {
    expect(passwordPresentation({ password_status: "saved" })).toMatchObject({ severity: "ok" });
    expect(passwordPresentation({ password_mismatch: true })).toMatchObject({ severity: "warning" });
    expect(settingsPresentation({ settings_saved: false })).toMatchObject({ severity: "error" });
  });

  it("uses the same Italian status language for failed synchronizations", () => {
    expect(syncPresentation({ id: "linked", name: "Condiviso", is_linked: true, last_sync_status: "failed", users: [user] }))
      .toEqual({ label: "Errore di sincronizzazione", severity: "error" });
    expect(syncPresentation({ id: "linked", name: "Condiviso", is_linked: true, last_sync_status: "running", users: [user] }))
      .toEqual({ label: "Sincronizzazione", severity: "info" });
    expect(syncPresentation({ id: "linked", name: "Condiviso", is_linked: true, auto_sync: true, last_sync_status: "skipped", users: [user] }))
      .toEqual({ label: "Sincronizzazione da verificare", severity: "warning" });
    expect(syncPresentation({ id: "linked", name: "Condiviso", is_linked: true, auto_sync: false, last_sync_status: "success", users: [user] }))
      .toEqual({ label: "Automazione disattivata", severity: "neutral" });
  });

  it("keeps known idle group states neutral instead of unverified", () => {
    expect(syncPresentation({ id: "standalone", name: "Roy", is_linked: false, users: [user] }))
      .toEqual({ label: "Non associato", severity: "neutral" });
    expect(syncPresentation({ id: "linked", name: "Condiviso", is_linked: true, users: [user] }))
      .toEqual({ label: "Automazione disattivata", severity: "neutral" });
  });

  it("filters linked groups through their assigned icon profile", () => {
    const groups: EmbyUserGroup[] = [{ id: "linked", name: "Condiviso", is_linked: true, users: [user] }];
    expect(visibleUserGroups(groups, { ...filters, iconProfileIds: ["badge-green"] }, { "group:linked": "badge-green" })).toHaveLength(1);
    expect(visibleUserGroups(groups, { ...filters, iconProfileIds: ["none"] }, { "group:linked": "badge-green" })).toHaveLength(0);
  });

  it("filters individual members by icon profile inside an unlinked group", () => {
    const marta = { ...user, user_id: "u2", name: "Marta" };
    const groups: EmbyUserGroup[] = [{ id: "owners", name: "Proprietari", is_linked: false, is_owners: true, users: [user, marta] }];

    expect(
      visibleUserGroups(
        groups,
        { ...filters, iconProfileIds: ["badge-green"] },
        { "user:green:u1": "badge-green" },
      )[0].users,
    ).toEqual([user]);
    expect(
      visibleUserGroups(
        groups,
        { ...filters, iconProfileIds: ["none"] },
        { "user:green:u1": "badge-green" },
      )[0].users,
    ).toEqual([marta]);
  });

  it("keeps the legacy server-first ordering choices", () => {
    const groups: EmbyUserGroup[] = [
      { id: "marta", name: "Marta", is_linked: false, users: [{ ...user, user_id: "u2", server_name: "Green" }] },
      { id: "roy", name: "Roy", is_linked: false, users: [user] },
    ];

    expect(visibleUserGroups(groups, { ...filters, sort: "server_asc_name_desc" }).map((group) => group.name)).toEqual(["Roy", "Marta"]);
  });
});
