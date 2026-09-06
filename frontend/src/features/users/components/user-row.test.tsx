import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import { UserRow } from "@/features/users/components/user-row";

const user = {
  server_id: "green",
  server_name: "Green",
  user_id: "owner-1",
  name: "Amministratore",
  is_disabled: false,
  is_user_disabled: false,
  is_remote_disabled: false,
  enable_remote_access: true,
  enable_downloading: true,
  is_admin: true,
  is_leader: false,
  password_status: "saved",
  settings_status: "saved",
};

const actions = {
  onToggle: () => undefined,
  onToggleRemote: () => undefined,
  onToggleDownload: () => undefined,
  onPassword: () => undefined,
  onSettings: () => undefined,
  onRename: () => undefined,
  onClone: () => undefined,
  onDelete: () => undefined,
  onUnlink: () => undefined,
  onMakeLeader: () => undefined,
  onDetails: () => undefined,
};

describe("UserRow", () => {
  it("keeps owner management actions while excluding lifecycle and access controls", () => {
    const markup = renderToStaticMarkup(
      <UserRow user={user} checked={false} linked={false} isOwner changing={false} groupSyncing={false} settingsSyncing={false} {...actions} />,
    );

    expect(markup).toContain("Gestisci password di Amministratore");
    expect(markup).toContain("user-row-shortcut--password user-row-shortcut--ok");
    expect(markup).toContain("Gestisci impostazioni Emby di Amministratore");
    expect(markup).toContain("Rinomina utente");
    expect(markup).not.toContain("Disabilita accesso remoto");
    expect(markup).not.toContain("Disabilita download");
    expect(markup).not.toContain("Clona utente");
    expect(markup).not.toContain("Elimina utente");
  });

  it("exposes the password status as a visual severity class", () => {
    const markup = renderToStaticMarkup(
      <UserRow
        user={{ ...user, name: "Luca", password_status: "mismatch" }}
        checked={false}
        linked={false}
        isOwner={false}
        changing={false}
        groupSyncing={false}
        settingsSyncing={false}
        {...actions}
      />,
    );

    expect(markup).toContain("user-row-shortcut--password user-row-shortcut--warning");
  });

  it("keeps unrelated shortcuts available while blocking structural and settings changes during group sync", () => {
    const markup = renderToStaticMarkup(
      <UserRow
        user={{ ...user, is_admin: false, is_leader: false, name: "Luca" }}
        checked={false}
        linked
        isOwner={false}
        changing={false}
        groupSyncing
        settingsSyncing
        {...actions}
      />,
    );

    expect(markup).toMatch(/aria-label="Gestisci impostazioni Emby di Luca:[^"]*"[^>]*disabled=""/);
    expect(markup).toMatch(/aria-label="Imposta Luca come leader"[^>]*disabled=""/);
    expect(markup).toMatch(/aria-label="Dissocia Luca dal gruppo"[^>]*disabled=""/);
    expect(markup).toContain("Clona utente");
    expect(markup).toMatch(/<button[^>]*disabled=""[^>]*>[\s\S]*?<span>Elimina utente<\/span><\/button>/);
    expect(markup).toContain('aria-label="Disabilita accesso remoto"');
  });

  it("keeps the leader star in the same quick-action grid slot as other members", () => {
    const markup = renderToStaticMarkup(
      <UserRow
        user={{ ...user, is_admin: false, is_leader: true, name: "Luca" }}
        checked={false}
        linked
        isOwner={false}
        changing={false}
        groupSyncing={false}
        settingsSyncing={false}
        {...actions}
      />,
    );

    const shortcutsStart = markup.indexOf('class="user-row-shortcuts"');
    const leaderStar = markup.indexOf('class="user-row-leader-state"');

    expect(leaderStar).toBeGreaterThan(shortcutsStart);
    expect(markup).toContain('class="user-row-shortcuts user-row-shortcuts--linked"');
    expect(markup).toContain("user-row-shortcut--password");
    expect(markup).toContain("user-row-shortcut--settings");
    expect(markup).toContain('aria-label="Leader del gruppo"');
  });

  it("shows an assigned icon profile before the original Emby avatar", () => {
    const markup = renderToStaticMarkup(
      <UserRow user={{ ...user, image_url: "/emby/admin.jpg" }} avatarUrl="/api/emby/icons/image/family/green?v=8" checked={false} linked={false} isOwner changing={false} groupSyncing={false} settingsSyncing={false} {...actions} />,
    );

    expect(markup).toContain('src="/api/emby/icons/image/family/green?v=8"');
    expect(markup).not.toContain('src="/emby/admin.jpg"');
  });

  it("keeps the configured Emby server identity visible in the compact card", () => {
    const markup = renderToStaticMarkup(
      <UserRow
        user={{
          ...user,
          server_alias: "Green",
          server_icon: "fa-server",
          server_icon_color: "#13a86b",
          server_icon_style: "regular",
        }}
        checked={false}
        linked={false}
        isOwner
        changing={false}
        groupSyncing={false}
        settingsSyncing={false}
        {...actions}
      />,
    );

    expect(markup).toContain('class="user-row-server"');
    expect(markup).toContain("Green");
    expect(markup).toContain('data-prefix="fas"');
  });

  it("exposes the compact actions panel through an explicit trigger relationship", () => {
    const markup = renderToStaticMarkup(
      <UserRow user={user} checked={false} linked={false} isOwner changing={false} groupSyncing={false} settingsSyncing={false} {...actions} />,
    );

    expect(markup).toContain('aria-label="Altre azioni per Amministratore"');
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).toMatch(/aria-controls="([^"]+)"/);
    expect(markup).toMatch(/<div id="[^"]+" class="user-row-menu-panel">/);
  });

  it("does not expose selection controls to a viewer", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilitiesProvider canMutate={false}>
        <UserRow user={user} checked={false} linked={false} isOwner changing={false} groupSyncing={false} settingsSyncing={false} {...actions} />
      </WorkspaceCapabilitiesProvider>,
    );

    expect(markup).not.toContain("Seleziona Amministratore");
    expect(markup).not.toContain('class="user-select"');
    expect(markup).toContain("user-row--read-only");
    expect(markup).toContain("Apri dettagli di Amministratore");
  });
});
