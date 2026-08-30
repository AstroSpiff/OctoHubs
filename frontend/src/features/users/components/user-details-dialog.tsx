import { Copy, KeyRound, Pencil, Trash2 } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { Severity } from "@/components/ui/badge";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import { getUserDetails } from "@/features/users/api";
import { formatUserTime, passwordPresentation } from "@/features/users/presentation";
import type { EmbyUser, EmbyUserDetails } from "@/features/users/types";

type UserDetailsDialogProps = {
  user: EmbyUser | null;
  avatarUrl?: string;
  isOwner?: boolean;
  changing?: boolean;
  onClose: () => void;
  onRename?: () => void;
  onPassword?: () => void;
  onClone?: () => void;
  onDelete?: () => void;
};

function UserDetailsDialog({
  user,
  avatarUrl,
  isOwner = false,
  changing = false,
  onClose,
  onRename,
  onPassword,
  onClone,
  onDelete,
}: UserDetailsDialogProps) {
  const [details, setDetails] = useState<EmbyUserDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return undefined;
    let active = true;
    setDetails(null);
    setLoading(true);
    setError("");

    getUserDetails(user)
      .then((result) => {
        if (active) setDetails(result);
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [user]);

  if (!user) return null;
  const hasPassword = details?.has_password ?? user.has_password;
  const password = passwordPresentation(user);

  return (
    <DialogBackdrop className="users-dialog-backdrop" onDismiss={onClose}>
      <section
        className="users-compact-dialog users-details-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="user-details-title"
      >
        <header className="users-details-header">
          <span className="users-details-avatar" aria-hidden="true">
            {avatarUrl || user.image_url ? (
              <img src={avatarUrl || user.image_url} alt="" />
            ) : (
              user.name.slice(0, 1).toUpperCase()
            )}
          </span>
          <div>
            <h2 id="user-details-title" className="contextual-heading" title="Profilo Emby">{user.name}</h2>
            <p className="users-details-server">
              <EmbyServerIcon
                icon={user.server_icon}
                color={user.server_icon_color}
                iconStyle={user.server_icon_style}
                size={15}
              />
              {user.server_alias || user.server_name}
            </p>
          </div>
        </header>
        {loading ? <p className="user-settings-loading">Caricamento dettagli...</p> : null}
        {error ? <p className="users-dialog-error" role="alert">{error}</p> : null}
        <dl className="users-details-grid">
          <Detail label="Ultimo accesso" value={formatUserTime(user.last_login)} />
          <Detail label="Ultima attività" value={formatUserTime(details?.last_activity_date)} />
          <Detail label="Creato" value={formatUserTime(details?.date_created)} />
          <Detail
            label="Password"
            value={`${password.label}. Emby: ${hasPassword ? "presente" : "assente"}`}
            severity={password.severity}
          />
          <Detail label="Ultimo contenuto" value={details?.last_played_title || "Mai"} />
          <Detail
            label="Ultima riproduzione"
            value={details?.last_played_date ? formatUserTime(details.last_played_date) : "Mai"}
          />
          {details?.connect_user_name ? (
            <Detail label="Utente Emby Connect" value={details.connect_user_name} />
          ) : null}
          {details?.connect_link_type ? (
            <Detail label="Tipo collegamento Connect" value={details.connect_link_type} />
          ) : null}
        </dl>
        <footer className="users-details-footer">
          {onRename || onPassword || (!isOwner && (onClone || onDelete)) ? (
            <div className="users-details-actions" role="group" aria-label={`Azioni per ${user.name}`}>
              {onRename ? <Button type="button" requiresWriteAccess variant="ghost" size="compact" onClick={onRename} disabled={changing}><Pencil size={15} aria-hidden="true" />Rinomina</Button> : null}
              {onPassword ? <Button type="button" requiresWriteAccess variant="ghost" size="compact" onClick={onPassword} disabled={changing}><KeyRound size={15} aria-hidden="true" />Password</Button> : null}
              {!isOwner && onClone ? <Button type="button" requiresWriteAccess variant="ghost" size="compact" onClick={onClone} disabled={changing}><Copy size={15} aria-hidden="true" />Clona</Button> : null}
              {!isOwner && onDelete ? <Button type="button" requiresWriteAccess variant="ghost" size="compact" className="users-details-delete" onClick={onDelete} disabled={changing}><Trash2 size={15} aria-hidden="true" />Elimina</Button> : null}
            </div>
          ) : null}
          <Button autoFocus type="button" variant="primary" onClick={onClose}>
            Chiudi
          </Button>
        </footer>
      </section>
    </DialogBackdrop>
  );
}

function Detail({ label, value, severity }: { label: string; value: string; severity?: Severity }) {
  return (
    <div className={severity ? `users-details-grid-item--${severity}` : undefined}>
      <dt>{label}</dt>
      <dd title={value}>{value}</dd>
    </div>
  );
}

export { UserDetailsDialog };
