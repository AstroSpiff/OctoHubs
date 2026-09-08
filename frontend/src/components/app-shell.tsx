import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, type ReactNode } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { AccountMenu } from "@/components/account-menu";
import {
  isAuthenticatedAccessState,
  workspaceContentOwnerKey,
  workspaceAccessState,
  type WorkspaceAccessState,
} from "@/components/app-shell-access";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "@/components/ui/icons";
import { EmbyWorkspaceHeader } from "@/features/emby-navigation/components/emby-workspace-header";
import { synchronizeAccountQueryCacheOwner } from "@/features/account-management/account-query-cache";
import { MobilePrimaryNavigation } from "@/features/navigation/components/mobile-primary-navigation";
import { NavigationPreferencesDialog } from "@/features/navigation/components/navigation-preferences-dialog";
import { PrimaryNavigationLinks } from "@/features/navigation/components/primary-navigation-links";
import { NavigationPreferencesProvider } from "@/features/navigation/navigation-preferences-provider";
import { useNavigationPreferences } from "@/features/navigation/use-navigation-preferences";
import { applicationTitle } from "@/features/navigation/application-title";
import { sessionRoleLabel } from "@/features/navigation/session-role-label";
import { OperationsCenter } from "@/features/operations/components/operations-center";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import { useOwnerBoundDisclosure } from "@/features/session/use-owner-bound-disclosure";
import { useApplicationTheme } from "@/hooks/use-application-theme";
import { getSession, type Session } from "@/lib/session";
import { cn } from "@/lib/utils";
import { useDeepLinkFocus } from "@/lib/use-deep-link-focus";

function AppShell() {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: getSession,
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const { pathname, search } = useLocation();
  const { theme, toggleTheme } = useApplicationTheme();
  const accessState = workspaceAccessState(session);
  const hasAuthenticatedAccess = isAuthenticatedAccessState(accessState);
  const accountId = hasAuthenticatedAccess ? session.data?.user.id ?? null : null;
  const currentOwnerKey = hasAuthenticatedAccess
    ? workspaceContentOwnerKey(accessState, session.data?.user)
    : null;
  const preferencesDialog = useOwnerBoundDisclosure(currentOwnerKey);
  const navigationPreferences = useNavigationPreferences(session.data?.preferences, accountId);
  useDeepLinkFocus(search);

  useLayoutEffect(() => {
    synchronizeAccountQueryCacheOwner(queryClient, accountId);
  }, [accountId, queryClient]);

  useEffect(() => {
    document.title = applicationTitle(pathname);
  }, [pathname]);

  return (
    <NavigationPreferencesProvider value={navigationPreferences}>
      <div
        className={cn(
          "app-shell",
          `app-shell--primary-${navigationPreferences.preferences.primary_navigation}`,
        )}
      >
        <a className="skip-link" href="#app-content">Vai al contenuto</a>
        <aside className="app-sidebar">
          <BrandLockup />
          <PrimaryNavigationLinks
            accountId={accountId}
            pathname={pathname}
            variant="sidebar"
            showSecondaryMenu={navigationPreferences.preferences.secondary_navigation === "sidebar"}
          />
          <SessionSummary
            session={session.data}
            theme={theme}
            onToggleTheme={toggleTheme}
            onOpenPreferences={preferencesDialog.open}
          />
        </aside>

        <header className="app-topbar">
          <BrandLockup compact />
          <PrimaryNavigationLinks
            accountId={accountId}
            pathname={pathname}
            variant="top"
            showSecondaryMenu={navigationPreferences.preferences.secondary_navigation === "sidebar"}
          />
          <SessionSummary
            session={session.data}
            theme={theme}
            onToggleTheme={toggleTheme}
            onOpenPreferences={preferencesDialog.open}
            compact
          />
        </header>

        <main id="app-content" className="app-main" tabIndex={-1}>
          <div className="app-workspace-layout">
            <EmbyWorkspaceHeader variant={navigationPreferences.preferences.secondary_navigation} />
            <WorkspaceCapabilityBoundary
              accountId={accountId}
              accessState={accessState}
              onRetry={() => void session.refetch()}
            >
              <Outlet key={workspaceContentOwnerKey(accessState, session.data?.user)} />
            </WorkspaceCapabilityBoundary>
          </div>
        </main>
        <MobilePrimaryNavigation accountId={accountId} pathname={pathname} />
        {accessState === "editor" && !isUsersPath(pathname) ? (
          <WorkspaceCapabilitiesProvider accountId={accountId} canMutate>
            <OperationsCenter key={currentOwnerKey} />
          </WorkspaceCapabilitiesProvider>
        ) : null}
      </div>
      <NavigationPreferencesDialog
        open={preferencesDialog.isOpen}
        preferences={navigationPreferences.preferences}
        isSaving={navigationPreferences.isSaving}
        error={navigationPreferences.error}
        onClose={preferencesDialog.close}
        onUpdate={navigationPreferences.updatePreferences}
      />
    </NavigationPreferencesProvider>
  );
}

function WorkspaceCapabilityBoundary({
  accountId = null,
  accessState,
  children,
  onRetry,
}: {
  accountId?: number | null;
  accessState: WorkspaceAccessState;
  children: ReactNode;
  onRetry?: () => void;
}) {
  const canMutate = accessState === "editor";
  return (
    <WorkspaceCapabilitiesProvider accountId={accountId} canMutate={canMutate}>
      <div className={cn("app-route-content", !canMutate && "app-route-content--read-only")}>
        {accessState === "loading" ? (
          <div className="app-read-only-notice" role="status">
            Verifica della sessione in corso: le azioni protette restano nascoste.
          </div>
        ) : null}
        {accessState === "error" ? (
          <div className="app-read-only-notice app-read-only-notice--error" role="alert">
            <span>Impossibile verificare i permessi della sessione. Le azioni protette restano nascoste.</span>
            {onRetry ? (
              <Button type="button" variant="secondary" size="compact" onClick={onRetry}>
                <RefreshCw size={14} aria-hidden="true" /> Riprova
              </Button>
            ) : null}
          </div>
        ) : null}
        {accessState === "viewer" ? (
          <div className="app-read-only-notice" role="status">
            Account in sola lettura: le azioni che modificano dati non sono disponibili.
          </div>
        ) : null}
        {children}
      </div>
    </WorkspaceCapabilitiesProvider>
  );
}

function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link
      className={cn("brand-lockup", compact && "brand-lockup--compact")}
      to="/emby-live"
      aria-label="OctoHubs, apri Emby Toolkit"
    >
      <span className="brand-mark" aria-hidden="true">OH</span>
      <span className="brand-copy">
        <strong>OctoHubs</strong>
        <small>Centro di controllo</small>
      </span>
    </Link>
  );
}

function SessionSummary({
  compact = false,
  onOpenPreferences,
  onToggleTheme,
  session,
  theme,
}: {
  compact?: boolean;
  onOpenPreferences: () => void;
  onToggleTheme: () => void;
  session: Session | undefined;
  theme: "light" | "dark";
}) {
  const user = session?.user;
  return (
    <div className={cn("session-summary", compact && "session-summary--compact")}>
      <WorkspaceCapabilitiesProvider accountId={user?.id ?? null} canMutate={user?.role !== "viewer"}>
        <AccountMenu
          key={user?.id ?? "anonymous"}
          compact={compact}
          onOpenPreferences={onOpenPreferences}
          onToggleTheme={onToggleTheme}
          roleLabel={sessionRoleLabel(user?.role)}
          theme={theme}
          username={user?.username}
        />
      </WorkspaceCapabilitiesProvider>
    </div>
  );
}

function isUsersPath(pathname: string) {
  return pathname === "/users" || pathname.startsWith("/users/");
}

export { AppShell, WorkspaceCapabilityBoundary };
