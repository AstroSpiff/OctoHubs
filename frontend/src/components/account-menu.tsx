import { ChevronDown, LogOut, Moon, Settings2, Sun, X } from "@/components/ui/icons";
import { createPortal } from "react-dom";
import { useLayoutEffect, useState } from "react";

import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { usePopoverDisclosure } from "@/components/ui/use-popover-disclosure";
import { logoutCurrentSession } from "@/features/account-management/api";
import { useMobileNavigationMode } from "@/features/navigation/use-mobile-navigation-mode";
import {
  isOwnerBoundBrowserActionCancelled,
  useOwnerBoundBrowserAction,
} from "@/features/session/use-owner-bound-browser-action";
import { navigateBrowser } from "@/lib/browser-download";
import { focusFirstRendered } from "@/lib/focus-target";
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
  const isMobile = useMobileNavigationMode();
  const [mobileOpen, setMobileOpen] = useState(false);
  const restoreDesktopFocus = !isMobile && mobileOpen;

  if (isMobile) {
    return (
      <MobileAccountMenu
        {...props}
        open={mobileOpen}
        onOpenChange={setMobileOpen}
      />
    );
  }
  return (
    <DesktopAccountMenu
      {...props}
      focusOnMount={restoreDesktopFocus}
      onFocusRestored={() => setMobileOpen(false)}
    />
  );
}

function DesktopAccountMenu({
  compact = false,
  onOpenPreferences,
  onToggleTheme,
  roleLabel,
  theme,
  username,
  focusOnMount = false,
  onFocusRestored,
}: AccountMenuProps & { focusOnMount?: boolean; onFocusRestored?: () => void }) {
  const menu = usePopoverDisclosure();
  const displayName = username || "Sessione";

  useLayoutEffect(() => {
    if (!focusOnMount) return;
    focusFirstRendered(
      document.querySelectorAll<HTMLElement>('[data-account-menu-trigger="desktop"]'),
      document.getElementById("app-content"),
    );
    onFocusRestored?.();
  }, [focusOnMount, menu.summaryRef, onFocusRestored]);

  return (
    <details
      ref={menu.detailsRef}
      className={cn("session-account-menu", compact && "session-account-menu--compact")}
      onToggle={menu.onToggle}
    >
      <summary
        ref={menu.summaryRef}
        data-account-menu-trigger="desktop"
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
  open,
  onOpenChange,
}: AccountMenuProps & { open: boolean; onOpenChange: (open: boolean) => void }) {
  const displayName = username || "Sessione";

  function close() {
    onOpenChange(false);
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
        onClick={() => onOpenChange(true)}
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
  const beginBrowserAction = useOwnerBoundBrowserAction();

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
    const action = beginBrowserAction();
    setLoggingOut(true);
    setLogoutError("");
    try {
      const redirect = await logoutCurrentSession(action.signal);
      action.assertCurrent();
      onAction?.();
      navigateBrowser(redirect, action);
    } catch (error) {
      if (isOwnerBoundBrowserActionCancelled(error)) return;
      try {
        action.assertCurrent();
      } catch (ownerError) {
        if (isOwnerBoundBrowserActionCancelled(ownerError)) return;
        throw ownerError;
      }
      setLogoutError(error instanceof Error ? error.message : "Disconnessione non riuscita.");
      setLoggingOut(false);
    } finally {
      action.release();
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

export { AccountMenu };
