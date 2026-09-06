import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createAccount,
  createApiToken,
  deleteAccount,
  exportApiTokenAudit,
  getAccounts,
  getApiTokenAudit,
  getApiTokens,
  getCurrentAccount,
  revokeApiToken,
  rotateApiToken,
  updateAccount,
  updateCurrentPassword,
} from "@/features/account-management/api";
import { accountQueryKeys } from "@/features/account-management/account-query-cache";
import type { ApiTokenAuditFilters, CreateApiTokenInput, CreateOctoHubsAccountInput, UpdateOctoHubsAccountInput } from "@/features/account-management/types";
import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";
import { useSensitiveMutation } from "@/lib/use-sensitive-mutation";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";

function useApiTokenAudit(filters: ApiTokenAuditFilters, enabled: boolean) {
  const { accountId } = useWorkspaceCapabilities();
  return useQuery({
    queryKey: accountQueryKeys.tokenAudit(accountId ?? 0, filters),
    queryFn: () => getApiTokenAudit(filters),
    enabled: enabled && accountId != null,
  });
}

function useAccountManagement() {
  const { accountId, canMutate } = useWorkspaceCapabilities();
  const client = useQueryClient();
  const accountOperations = useKeyedOperationState();
  const owner = accountId ?? 0;
  const profile = useQuery({
    queryKey: accountQueryKeys.profile(owner),
    queryFn: getCurrentAccount,
    enabled: accountId != null,
  });
  const accounts = useQuery({
    queryKey: accountQueryKeys.accounts(owner),
    queryFn: getAccounts,
    enabled: accountId != null && canMutate && profile.data?.role === "admin",
  });
  const apiTokens = useQuery({
    queryKey: accountQueryKeys.tokens(owner),
    queryFn: getApiTokens,
    enabled: accountId != null && Boolean(profile.data),
  });
  const invalidateAccounts = () => client.invalidateQueries({ queryKey: accountQueryKeys.all(owner) });
  const invalidateApiTokens = () => {
    void client.invalidateQueries({ queryKey: accountQueryKeys.tokens(owner) });
    void client.invalidateQueries({ queryKey: accountQueryKeys.tokenAudits(owner) });
  };
  const updatePassword = useSensitiveMutation({ mutationFn: updateCurrentPassword });
  const createToken = useSensitiveMutation({
    mutationFn: createApiToken,
    onSuccess: invalidateApiTokens,
  });
  const revokeToken = useMutation({
    mutationFn: revokeApiToken,
    onSuccess: invalidateApiTokens,
  });
  const rotateToken = useSensitiveMutation({
    mutationFn: rotateApiToken,
    onSuccess: invalidateApiTokens,
    publicVariables: (tokenId) => tokenId,
  });
  const create = useSensitiveMutation({
    mutationFn: createAccount,
    onSuccess: invalidateAccounts,
  });
  const update = useSensitiveMutation({
    mutationFn: ({ accountId, input }: { accountId: number; input: UpdateOctoHubsAccountInput }) => updateAccount(accountId, input),
    onSuccess: invalidateAccounts,
  });
  const remove = useMutation({
    mutationFn: deleteAccount,
    onSuccess: invalidateAccounts,
  });

  async function runAccountOperation<T>(accountId: number, operation: () => Promise<T>): Promise<T | undefined> {
    const key = String(accountId);
    if (accountOperations.isPending(key)) return undefined;
    accountOperations.begin([key]);
    try {
      return await operation();
    } catch (error) {
      accountOperations.fail([key], error);
      throw error;
    } finally {
      accountOperations.finish([key]);
    }
  }

  return {
    accounts,
    accountOperations,
    create,
    apiTokens,
    createToken,
    profile,
    remove,
    revokeToken,
    rotateToken,
    update,
    updatePassword,
    createAccount: (input: CreateOctoHubsAccountInput) => create.mutateAsync(input),
    deleteAccount: (accountId: number) =>
      runAccountOperation(accountId, () => remove.mutateAsync(accountId)),
    createApiToken: (input: CreateApiTokenInput) => createToken.mutateAsync(input),
    exportApiTokenAudit,
    updateAccount: (accountId: number, input: UpdateOctoHubsAccountInput) =>
      runAccountOperation(accountId, () => update.mutateAsync({ accountId, input })),
  };
}

export { useAccountManagement, useApiTokenAudit };
