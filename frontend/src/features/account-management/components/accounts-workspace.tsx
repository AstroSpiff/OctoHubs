import { useState } from "react";

import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspaceSection } from "@/components/ui/workspace-layout";
import { AccountManagementPanel } from "@/features/account-management/components/account-management-panel";
import { AccountProfilePanel } from "@/features/account-management/components/account-profile-panel";
import { ApiTokenPanel } from "@/features/account-management/components/api-token-panel";
import { ApiTokenAuditPanel } from "@/features/account-management/components/api-token-audit-panel";
import type { ApiTokenAuditFilters } from "@/features/account-management/types";
import { useAccountManagement, useApiTokenAudit } from "@/features/account-management/use-account-management";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";

function AccountsWorkspace({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void } = {}) {
  const accounts = useAccountManagement();
  const { canMutate } = useWorkspaceCapabilities();
  const profile = accounts.profile.data;
  const [auditFilters, setAuditFilters] = useState<ApiTokenAuditFilters>({});
  const audit = useApiTokenAudit(auditFilters, Boolean(profile));
  const resetManagementErrors = (accountId?: number) => {
    accounts.create.reset();
    accounts.update.reset();
    accounts.remove.reset();
    accounts.accountOperations.clear(accountId === undefined ? undefined : [String(accountId)]);
  };
  const resetTokenErrors = () => {
    accounts.createToken.reset();
    accounts.revokeToken.reset();
    accounts.rotateToken.reset();
  };

  return (
    <WorkspaceSection className="accounts-workspace">
      <WorkspaceHeading level="section" context="Amministrazione" title="Accessi OctoHubs" description="Gestisci credenziali e preferenze personali senza modificare i dati operativi condivisi dell'istanza." />
      <QueryStateBoundary error={accounts.profile.error} hasData={Boolean(profile)} loadingLabel="Caricamento account..." retrying={accounts.profile.isFetching} onRetry={() => void accounts.profile.refetch()}>
        {profile ? <>
          <AccountProfilePanel account={profile} error={accounts.updatePassword.error?.message} saving={accounts.updatePassword.isPending} onChangePassword={accounts.updatePassword.mutateAsync} />
          <QueryStateBoundary error={accounts.apiTokens.error} hasData={Boolean(accounts.apiTokens.data)} loadingLabel="Caricamento token API..." retrying={accounts.apiTokens.isFetching} onRetry={() => void accounts.apiTokens.refetch()}>
            {accounts.apiTokens.data ? <ApiTokenPanel
              availablePermissionProfiles={accounts.apiTokens.data.available_permission_profiles}
              tokens={accounts.apiTokens.data.tokens}
              loading={accounts.apiTokens.isLoading}
              creating={accounts.createToken.isPending}
              actionPending={
                accounts.createToken.isPending ||
                accounts.revokeToken.isPending ||
                accounts.rotateToken.isPending
              }
              revokingTokenId={accounts.revokeToken.isPending ? accounts.revokeToken.variables : undefined}
              rotatingTokenId={accounts.rotateToken.isPending ? accounts.rotateToken.variables : undefined}
              error={(accounts.createToken.error || accounts.revokeToken.error || accounts.rotateToken.error)?.message}
              onResetErrors={resetTokenErrors}
              onCreate={(input) => { resetTokenErrors(); return accounts.createApiToken(input); }}
              onRevoke={(tokenId) => { resetTokenErrors(); return accounts.revokeToken.mutateAsync(tokenId); }}
              onRotate={(tokenId) => { resetTokenErrors(); return accounts.rotateToken.mutateAsync(tokenId); }}
              onSecretPendingChange={onDirtyChange}
            /> : null}
          </QueryStateBoundary>
          <QueryStateBoundary error={audit.error} hasData={Boolean(audit.data)} loadingLabel="Caricamento audit token..." retrying={audit.isFetching} onRetry={() => void audit.refetch()}>
            {audit.data ? <ApiTokenAuditPanel
              events={audit.data.events}
              filters={auditFilters}
              loading={audit.isLoading}
              tokens={accounts.apiTokens.data?.tokens || []}
              onChangeFilters={setAuditFilters}
              onExport={accounts.exportApiTokenAudit}
              onRefresh={() => void audit.refetch()}
            /> : null}
          </QueryStateBoundary>
          {canMutate && profile.role === "admin" ? <QueryStateBoundary error={accounts.accounts.error} hasData={Boolean(accounts.accounts.data)} loadingLabel="Caricamento accessi OctoHubs..." retrying={accounts.accounts.isFetching} onRetry={() => void accounts.accounts.refetch()}>
            {accounts.accounts.data ? <AccountManagementPanel
              accounts={accounts.accounts.data}
              busyAccountIds={accounts.accountOperations.pendingKeys}
              creating={accounts.create.isPending}
              currentAccountId={profile.id}
              createError={accounts.create.error?.message}
              operationErrors={accounts.accountOperations.errors}
              loading={accounts.accounts.isLoading}
              onResetErrors={resetManagementErrors}
              onCreate={(input) => { resetManagementErrors(); return accounts.createAccount(input); }}
              onDelete={accounts.deleteAccount}
              onUpdate={accounts.updateAccount}
            /> : null}
          </QueryStateBoundary> : null}
        </> : null}
      </QueryStateBoundary>
    </WorkspaceSection>
  );
}

export { AccountsWorkspace };
