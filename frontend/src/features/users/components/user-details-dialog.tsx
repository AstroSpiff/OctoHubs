import { Copy, KeyRound, Pencil, Trash2 } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { Severity } from "@/components/ui/badge";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import { getUserDetails } from "@/features/users/api";
import { formatUserTime, passwordPresentation } from "@/features/users/presentation";
import type { EmbyUser, EmbyUserDetails } from "@/features/users/types";
import { errorMessage, type AuthoritativeSnapshot } from "@/lib/authoritative-snapshot";

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
  const [snapshot, setSnapshot] = useState<AuthoritativeSnapshot<EmbyUserDetails> & {
    targetKey: string;
  }>({ status: "pending", targetKey: "" });
  const [loadVersion, setLoadVersion] = useState(0);
  const targetKey = user ? `${user.server_id}:${user.user_id}` : "";

  useEffect(() => {
    if (!user) return undefined;
    let active = true;
    setSnapshot({ status: "pending", targetKey });

    getUserDetails(user)
      .then((result) => {
        if (active) {
          setSnapshot({
            status: "success",
            targetKey,
            data: result,
          });
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setSnapshot({
            status: "error",
            targetKey,
            error: errorMessage(reason, "Impossibile caricare i dettagli utente."),
          });
        }
      });

    return () => {
      active = false;
    };
  }, [loadVersion, targetKey, user]);

  if (!user) return null;
  const currentSnapshot = snapshot.targetKey === targetKey ? snapshot : undefined;
  const details = currentSnapshot?.status === "success"
    ? currentSnapshot.data
    : undefined;
  const loading = !currentSnapshot || currentSnapshot.status === "pending";
  const hasPassword = details?.has_password ?? user.has_password;
  const password = passwordPresentation(user);
  const embyPasswordLabel = hasPassword === undefined
    ? "non disponibile"
    : hasPassword
      ? "presente"
      : "assente";

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
        {currentSnapshot?.status === "error" ? (
          <div className="users-dialog-error" role="alert">
            <span>{currentSnapshot.error}</span>{" "}
            <Button type="button" variant="secondary" size="compact" onClick={() => setLoadVersion((version) => version + 1)}>
              Riprova
            </Button>
          </div>
        ) : null}
        <dl className="users-details-grid">
          <Detail label="Ultimo accesso" value={formatUserTime(user.last_login)} />
          <Detail
            label="Password"
            value={`${password.label}. Emby: ${embyPasswordLabel}`}
            severity={password.severity}
          />
          {details ? (
            <>
              <Detail label="Ultima attività" value={formatUserTime(details.last_activity_date)} />
              <Detail label="Creato" value={formatUserTime(details.date_created)} />
              <Detail label="Ultimo contenuto" value={details.last_played_title || "Mai"} />
              <Detail
                label="Ultima riproduzione"
                value={details.last_played_date ? formatUserTime(details.last_played_date) : "Mai"}
              />
              {details.connect_user_name ? (
                <Detail label="Utente Emby Connect" value={details.connect_user_name} />
              ) : null}
              {details.connect_link_type ? (
                <Detail label="Tipo collegamento Connect" value={details.connect_link_type} />
              ) : null}
            </>
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
