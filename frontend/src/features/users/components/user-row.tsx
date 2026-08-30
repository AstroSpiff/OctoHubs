import {
  Ban,
  CircleEllipsis,
  Copy,
  Download,
  KeyRound,
  Link2Off,
  MoreHorizontal,
  Pencil,
  Settings2,
  Star,
  StarRegular,
  ShieldCheck,
  Trash2,
  Wifi,
  WifiOff,
} from "@/components/ui/icons";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { usePopoverDisclosure } from "@/components/ui/use-popover-disclosure";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import { accessPresentation, passwordPresentation, settingsPresentation } from "@/features/users/presentation";
import type { EmbyUser } from "@/features/users/types";

type UserRowProps = {
  user: EmbyUser;
  avatarUrl?: string;
  checked: boolean;
  linked: boolean;
  isOwner: boolean;
  onToggle: () => void;
  onToggleRemote: () => void;
  onToggleDownload: () => void;
  onPassword: () => void;
  onSettings: () => void;
  onRename: () => void;
  onClone: () => void;
  onDelete: () => void;
  onUnlink: () => void;
  onMakeLeader: () => void;
  onDetails: () => void;
  changing: boolean;
  groupSyncing: boolean;
  settingsSyncing: boolean;
};

function UserRow({
  user,
  avatarUrl,
  checked,
  linked,
  isOwner,
  onToggle,
  onToggleRemote,
  onToggleDownload,
  onPassword,
  onSettings,
  onRename,
  onClone,
  onDelete,
  onUnlink,
  onMakeLeader,
  onDetails,
  changing,
  groupSyncing,
  settingsSyncing,
}: UserRowProps) {
  const access = accessPresentation(user);
  const password = passwordPresentation(user);
  const settings = settingsPresentation(user);
  const canManage = !changing;
  const canManageStructure = !isOwner && !changing && !groupSyncing;
  const canManageSettings = !changing && !settingsSyncing;

  return (
    <article className="user-row">
      <label className="user-select">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={`Seleziona ${user.name}`}
        />
        <span />
      </label>
      <span className="user-avatar-wrap">
        {avatarUrl || user.image_url ? (
          <img src={avatarUrl || user.image_url} alt="" />
        ) : (
          <span className="user-avatar">
            {user.name.slice(0, 1).toUpperCase()}
          </span>
        )}
        <span
          className={`user-access-indicator user-access-indicator--${access.severity}`}
          title={access.label}
        >
          <span className="sr-only">{access.label}</span>
        </span>
      </span>
      <div className="user-row-identity">
        <div className="user-row-name-row">
          <button
            type="button"
            className="user-row-name"
            title={`Apri dettagli di ${user.name}`}
            onClick={onDetails}
          >
            <strong>{user.name}</strong>
            {user.is_admin ? (
              <ShieldCheck size={14} aria-label="Amministratore Emby" />
            ) : null}
          </button>
        </div>
        <span className="user-row-server">
          <EmbyServerIcon
            icon={user.server_icon}
            color={user.server_icon_color}
            iconStyle={user.server_icon_style}
            size={13}
          />
          {user.server_alias || user.server_name}
        </span>
      </div>
      <div className={`user-row-shortcuts${linked && !isOwner ? " user-row-shortcuts--linked" : ""}`} aria-label={`Permessi e azioni rapide di ${user.name}`}>
        {linked && !isOwner ? (
          user.is_leader ? (
            <span
              className="user-row-leader-state"
              title="Leader del gruppo"
              role="img"
              aria-label="Leader del gruppo"
            >
              <Star size={16} aria-hidden="true" />
            </span>
          ) : (
            <WriteAction>
              <button
                type="button"
                className="user-row-leader-action"
                title={
                  user.enable_remote_access
                    ? "Imposta come leader"
                    : "Impossibile impostare: connessione remota disabilitata"
                }
                aria-label={`Imposta ${user.name} come leader`}
                onClick={onMakeLeader}
                disabled={!canManageStructure || !user.enable_remote_access}
              >
                <StarRegular
                  size={16}
                  aria-hidden="true"
                />
              </button>
            </WriteAction>
          )
        ) : null}
        {!isOwner ? (
          <Button
            type="button"
            requiresWriteAccess
            variant="ghost"
            size="icon"
            className="user-row-shortcut"
            title={
              user.enable_remote_access
                ? "Disabilita accesso remoto"
                : "Abilita accesso remoto"
            }
            aria-label={
              user.enable_remote_access
                ? "Disabilita accesso remoto"
                : "Abilita accesso remoto"
            }
            onClick={onToggleRemote}
            disabled={!canManage}
          >
            {user.enable_remote_access ? (
              <Wifi size={16} aria-hidden="true" />
            ) : (
              <WifiOff size={16} aria-hidden="true" />
            )}
          </Button>
        ) : null}
        {!isOwner ? (
          <Button
            type="button"
            requiresWriteAccess
            variant="ghost"
            size="icon"
            className="user-row-shortcut"
            title={
              user.enable_downloading ? "Disabilita download" : "Abilita download"
            }
            aria-label={
              user.enable_downloading ? "Disabilita download" : "Abilita download"
            }
            onClick={onToggleDownload}
            disabled={!canManage}
          >
            {user.enable_downloading ? (
              <Download size={16} aria-hidden="true" />
            ) : (
              <span className="user-download-disabled" aria-hidden="true">
                <Download size={16} />
                <Ban size={15} />
              </span>
            )}
          </Button>
        ) : null}
        <Button
          type="button"
          requiresWriteAccess
          variant="ghost"
          size="icon"
          className={`user-row-shortcut user-row-shortcut--password user-row-shortcut--${password.severity}`}
          title={user.has_password === undefined ? password.label : `${password.label}. Emby: ${user.has_password ? "presente" : "assente"}`}
          aria-label={`Gestisci password di ${user.name}: ${password.label}`}
          onClick={onPassword}
          disabled={!canManage}
        >
          <KeyRound size={16} aria-hidden="true" />
        </Button>
        <Button
          type="button"
          requiresWriteAccess
          variant="ghost"
          size="icon"
          className={`user-row-shortcut user-row-shortcut--settings user-row-shortcut--${settings.severity}`}
          title={settings.label}
          aria-label={`Gestisci impostazioni Emby di ${user.name}: ${settings.label}`}
          onClick={onSettings}
          disabled={!canManageSettings}
        >
          <Settings2 size={16} aria-hidden="true" />
        </Button>
        {linked && !isOwner ? (
          <Button
            type="button"
            requiresWriteAccess
            variant="ghost"
            size="icon"
            className="user-row-shortcut user-row-shortcut--unlink"
            title="Dissocia dal gruppo"
            aria-label={`Dissocia ${user.name} dal gruppo`}
            onClick={onUnlink}
            disabled={!canManageStructure}
          >
            <Link2Off size={16} aria-hidden="true" />
          </Button>
        ) : null}
        <UserActionsMenu
          user={user}
          linked={linked}
          isOwner={isOwner}
          disabled={!canManage}
          settingsDisabled={!canManageSettings}
          structuralDisabled={!canManageStructure}
          onDetails={onDetails}
          onPassword={onPassword}
          onSettings={onSettings}
          onRename={onRename}
          onClone={onClone}
          onDelete={onDelete}
          onMakeLeader={onMakeLeader}
        />
      </div>
    </article>
  );
}

function UserActionsMenu({
  user,
  linked,
  isOwner,
  disabled,
  settingsDisabled,
  structuralDisabled,
  onDetails,
  onPassword,
  onSettings,
  onRename,
  onClone,
  onDelete,
  onMakeLeader,
}: Pick<
  UserRowProps,
  | "user"
  | "linked"
  | "isOwner"
  | "onDetails"
  | "onPassword"
  | "onSettings"
  | "onRename"
  | "onClone"
  | "onDelete"
  | "onMakeLeader"
> & { disabled: boolean; settingsDisabled: boolean; structuralDisabled: boolean }) {
  const menu = usePopoverDisclosure();

  return (
    <details
      ref={menu.detailsRef}
      className="user-row-menu"
      onToggle={menu.onToggle}
    >
      <summary
        ref={menu.summaryRef}
        title={`Altre azioni per ${user.name}`}
        aria-label={`Altre azioni per ${user.name}`}
        aria-controls={menu.contentId}
        aria-expanded={menu.open}
      >
        <MoreHorizontal size={18} aria-hidden="true" />
      </summary>
      <div id={menu.contentId} className="user-row-menu-panel">
        <MenuAction
          icon={<CircleEllipsis size={16} />}
          label="Dettagli utente"
          onClick={() => {
            menu.close();
            onDetails();
          }}
        />
        <MenuAction
          icon={<KeyRound size={16} />}
          label="Gestisci password"
          requiresWriteAccess
          onClick={() => {
            menu.close();
            onPassword();
          }}
          disabled={disabled}
        />
        <MenuAction
          icon={<Settings2 size={16} />}
          label="Impostazioni Emby"
          requiresWriteAccess
          onClick={() => {
            menu.close();
            onSettings();
          }}
          disabled={settingsDisabled}
        />
        <MenuAction
          icon={<Pencil size={16} />}
          label="Rinomina utente"
          requiresWriteAccess
          onClick={() => {
            menu.close();
            onRename();
          }}
          disabled={disabled}
        />
        {!isOwner ? (
          <MenuAction
            icon={<Copy size={16} />}
            label="Clona utente"
            requiresWriteAccess
            onClick={() => {
              menu.close();
              onClone();
            }}
            disabled={disabled}
          />
        ) : null}
        {linked && !isOwner && !user.is_leader ? (
          <MenuAction
            icon={<StarRegular size={16} />}
            label="Imposta come leader"
            requiresWriteAccess
            onClick={() => {
              menu.close();
              onMakeLeader();
            }}
            disabled={structuralDisabled || !user.enable_remote_access}
          />
        ) : null}
        {!isOwner ? (
          <MenuAction
            icon={<Trash2 size={16} />}
            label="Elimina utente"
            requiresWriteAccess
            onClick={() => {
              menu.close();
              onDelete();
            }}
            disabled={structuralDisabled}
            danger
          />
        ) : null}
      </div>
    </details>
  );
}

function MenuAction({
  icon,
  label,
  onClick,
  disabled = false,
  danger = false,
  requiresWriteAccess = false,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  requiresWriteAccess?: boolean;
}) {
  const action = (
    <button
      type="button"
      className={danger ? "is-danger" : ""}
      onClick={onClick}
      disabled={disabled}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
  return requiresWriteAccess ? <WriteAction>{action}</WriteAction> : action;
}

export { UserRow };
