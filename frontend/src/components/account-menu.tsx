import { ChevronDown, LogOut, Moon, Settings2, Sun, X } from "@/components/ui/icons";
import { createPortal } from "react-dom";
import { useEffect, useState } from "react";

import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { usePopoverDisclosure } from "@/components/ui/use-popover-disclosure";
import { logoutCurrentSession } from "@/features/account-management/api";
import type { ApplicationTheme } from "@/lib/theme-preference";
import { cn } from "@/lib/utils";

type AccountMenuProps = {
  compact?: boolean;
  onOpenPreferences: () => void;
  onToggleTheme: () => void;
  roleLabel: string;
  theme: ApplicationTheme;
  username?: string;
};

type AccountActionsProps = Pick<
  AccountMenuProps,
  "onOpenPreferences" | "onToggleTheme" | "theme"
> & {
  onAction?: () => void;
};

function AccountMenu(props: AccountMenuProps) {
  const isMobile = useMobileAccountMenu();

  if (isMobile) return <MobileAccountMenu {...props} />;
  return <DesktopAccountMenu {...props} />;
}

function DesktopAccountMenu({
  compact = false,
  onOpenPreferences,
  onToggleTheme,
  roleLabel,
  theme,
  username,
}: AccountMenuProps) {
  const menu = usePopoverDisclosure();
  const displayName = username || "Sessione";

  return (
    <details
      ref={menu.detailsRef}
      className={cn("session-account-menu", compact && "session-account-menu--compact")}
      onToggle={menu.onToggle}
    >
      <summary
        ref={menu.summaryRef}
        aria-controls={menu.contentId}
        aria-expanded={menu.open}
        aria-label={`Apri menu account di ${displayName}`}
        title="Menu account"
      >
        <AccountIdentity compact={compact} displayName={displayName} roleLabel={roleLabel} />
      </summary>
      <section id={menu.contentId} className="session-account-menu-panel" aria-label="Menu account">
        <AccountActions
          theme={theme}
          onAction={menu.close}
          onOpenPreferences={onOpenPreferences}
          onToggleTheme={onToggleTheme}
        />
      </section>
    </details>
  );
}

function MobileAccountMenu({
  onOpenPreferences,
  onToggleTheme,
  roleLabel,
  theme,
  username,
}: AccountMenuProps) {
  const [open, setOpen] = useState(false);
  const displayName = username || "Sessione";

  function close() {
    setOpen(false);
  }

  return (
    <>
      <button
        type="button"
        className="session-account-trigger session-account-trigger--compact"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`Apri menu account di ${displayName}`}
        title="Menu account"
        onClick={() => setOpen(true)}
      >
        <AccountAvatar displayName={displayName} />
      </button>
      {open && typeof document !== "undefined" ? createPortal(
        <AccountMenuSheet
          displayName={displayName}
          roleLabel={roleLabel}
          theme={theme}
          onClose={close}
          onOpenPreferences={onOpenPreferences}
          onToggleTheme={onToggleTheme}
        />,
        document.body,
      ) : null}
    </>
  );
}

function AccountMenuSheet({
  displayName,
  onClose,
  onOpenPreferences,
  onToggleTheme,
  roleLabel,
  theme,
}: AccountActionsProps & {
  displayName: string;
  onClose: () => void;
  roleLabel: string;
}) {
  return (
    <DialogBackdrop className="account-menu-backdrop" onDismiss={onClose}>
      <section className="account-menu-sheet" role="dialog" aria-modal="true" aria-labelledby="account-menu-title">
        <header>
          <div className="account-menu-sheet-identity">
            <AccountAvatar displayName={displayName} />
            <span>
              <strong id="account-menu-title">{displayName}</strong>
              <small>{roleLabel}</small>
            </span>
          </div>
          <button type="button" className="account-menu-close" onClick={onClose} aria-label="Chiudi menu account" title="Chiudi">
            <X size={19} aria-hidden="true" />
          </button>
        </header>
        <AccountActions
          theme={theme}
          onAction={onClose}
          onOpenPreferences={onOpenPreferences}
          onToggleTheme={onToggleTheme}
        />
      </section>
    </DialogBackdrop>
  );
}

function AccountIdentity({
  compact,
  displayName,
  roleLabel,
}: {
  compact: boolean;
  displayName: string;
  roleLabel: string;
}) {
  return (
    <>
      <AccountAvatar displayName={displayName} />
      {!compact ? (
        <span className="session-user">
          <strong>{displayName}</strong>
          <small>{roleLabel}</small>
        </span>
      ) : null}
      {!compact ? <ChevronDown className="session-account-menu-chevron" size={15} aria-hidden="true" /> : null}
    </>
  );
}

function AccountAvatar({ displayName }: { displayName: string }) {
  return <span className="session-avatar" aria-hidden="true">{displayName.slice(0, 1).toUpperCase() || "?"}</span>;
}

function AccountActions({ onAction, onOpenPreferences, onToggleTheme, theme }: AccountActionsProps) {
  const isDark = theme === "dark";
  const themeLabel = isDark ? "Attiva tema chiaro" : "Attiva tema scuro";
  const ThemeIcon = isDark ? Sun : Moon;
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");

  function openPreferences() {
    onAction?.();
    onOpenPreferences();
  }

  function toggleTheme() {
    onAction?.();
    onToggleTheme();
  }

  async function logout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setLogoutError("");
    try {
      const redirect = await logoutCurrentSession();
      onAction?.();
      window.location.assign(redirect);
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : "Disconnessione non riuscita.");
      setLoggingOut(false);
    }
  }

  return (
    <div className="session-account-menu-actions">
      <button type="button" className="session-account-menu-action" onClick={openPreferences}>
        <Settings2 size={16} aria-hidden="true" />
        <span>Preferenze interfaccia</span>
      </button>
      <button type="button" className="session-account-menu-action" onClick={toggleTheme}>
        <ThemeIcon size={16} aria-hidden="true" />
        <span>{themeLabel}</span>
      </button>
      <div className="session-account-menu-separator" aria-hidden="true" />
      <button
        type="button"
        className="session-account-menu-action is-danger"
        disabled={loggingOut}
        onClick={() => void logout()}
      >
        <LogOut size={16} aria-hidden="true" />
        <span>{loggingOut ? "Disconnessione..." : "Esci"}</span>
      </button>
      {logoutError ? <p className="session-account-menu-error" role="alert">{logoutError}</p> : null}
    </div>
  );
}

function useMobileAccountMenu() {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(max-width: 899px)").matches;
  });

  useEffect(() => {
    const query = window.matchMedia("(max-width: 899px)");
    const update = () => setIsMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return isMobile;
}

export { AccountMenu };
