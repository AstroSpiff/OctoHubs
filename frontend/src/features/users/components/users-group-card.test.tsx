import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { UsersGroupCard } from "@/features/users/components/users-group-card";

const group = {
  id: "family",
  name: "Famiglia",
  is_linked: true,
  users: [],
};

const actions = {
  onToggle: () => undefined,
  onToggleRemote: () => undefined,
  onToggleDownload: () => undefined,
  onConfigure: () => undefined,
  onSettings: () => undefined,
  onPassword: () => undefined,
  onRename: () => undefined,
  onDelete: () => undefined,
  onIconProfileChange: () => undefined,
  onUserPassword: () => undefined,
  onUserSettings: () => undefined,
  onUserRename: () => undefined,
  onUserClone: () => undefined,
  onUserDelete: () => undefined,
  onUserUnlink: () => undefined,
  onSetLeader: () => undefined,
  onUserDetails: () => undefined,
  onSaveSyncSettings: async () => undefined,
  onSync: () => undefined,
};

describe("UsersGroupCard", () => {
  it("locks the title rename action while the group is synchronizing", () => {
    const markup = renderToStaticMarkup(
      <UsersGroupCard
        group={group}
        selected={new Set()}
        iconConfig={{ profiles: [], matrix: {}, bindings: {} }}
        iconRevision={0}
        iconSaving={false}
        syncing
        savingSyncSettings={false}
        isUserChanging={() => false}
        {...actions}
      />,
    );

    expect(markup).toMatch(
      /aria-label="Rinomina gruppo Famiglia"[^>]*disabled=""/,
    );
    expect(markup).toContain("Icone");
  });

  it("keeps one contextual manual sync action when automation is enabled", () => {
    const markup = renderToStaticMarkup(
      <UsersGroupCard
        group={{ ...group, auto_sync: true }}
        selected={new Set()}
        iconConfig={{ profiles: [], matrix: {}, bindings: {} }}
        iconRevision={0}
        iconSaving={false}
        syncing={false}
        savingSyncSettings={false}
        isUserChanging={() => false}
        {...actions}
      />,
    );

    expect(markup).toContain('aria-label="Sincronizza ora Famiglia"');
    expect(markup).not.toContain('aria-label="Sincronizza gruppo adesso"');
  });
});
