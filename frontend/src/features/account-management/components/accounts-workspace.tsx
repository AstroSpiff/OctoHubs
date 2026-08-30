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

function AccountsWorkspace() {
  const accounts = useAccountManagement();
  const profile = accounts.profile.data;
  const [auditFilters, setAuditFilters] = useState<ApiTokenAuditFilters>({});
  const audit = useApiTokenAudit(auditFilters, Boolean(profile));
  const managementActionError = accounts.create.error || accounts.update.error || accounts.remove.error;
  const tokenActionError = accounts.createToken.error || accounts.revokeToken.error || accounts.rotateToken.error;

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
              revokingTokenId={accounts.revokeToken.variables}
              rotatingTokenId={accounts.rotateToken.variables}
              error={tokenActionError?.message}
              onCreate={accounts.createApiToken}
              onRevoke={accounts.revokeToken.mutateAsync}
              onRotate={accounts.rotateToken.mutateAsync}
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
          {profile.role === "admin" ? <QueryStateBoundary error={accounts.accounts.error} hasData={Boolean(accounts.accounts.data)} loadingLabel="Caricamento accessi OctoHubs..." retrying={accounts.accounts.isFetching} onRetry={() => void accounts.accounts.refetch()}>
            {accounts.accounts.data ? <AccountManagementPanel accounts={accounts.accounts.data} busyAccountId={accounts.update.variables?.accountId || accounts.remove.variables} creating={accounts.create.isPending} currentAccountId={profile.id} error={managementActionError?.message} loading={accounts.accounts.isLoading} onCreate={accounts.createAccount} onDelete={accounts.remove.mutateAsync} onUpdate={(accountId, input) => accounts.update.mutateAsync({ accountId, input })} /> : null}
          </QueryStateBoundary> : null}
        </> : null}
      </QueryStateBoundary>
    </WorkspaceSection>
  );
}

export { AccountsWorkspace };
