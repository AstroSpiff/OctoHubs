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
import type { ApiTokenAuditFilters, CreateApiTokenInput, CreateOctoHubsAccountInput, UpdateOctoHubsAccountInput } from "@/features/account-management/types";
import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";
import { useSensitiveMutation } from "@/lib/use-sensitive-mutation";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";

function useApiTokenAudit(filters: ApiTokenAuditFilters, enabled: boolean) {
  return useQuery({
    queryKey: ["account", "token-audit", filters.tokenId || null, filters.result || null, filters.apiVersion || null],
    queryFn: () => getApiTokenAudit(filters),
    enabled,
  });
}

function useAccountManagement() {
  const { canMutate } = useWorkspaceCapabilities();
  const client = useQueryClient();
  const accountOperations = useKeyedOperationState();
  const profile = useQuery({ queryKey: ["account", "me"], queryFn: getCurrentAccount });
  const accounts = useQuery({
    queryKey: ["account", "list"],
    queryFn: getAccounts,
    enabled: canMutate && profile.data?.role === "admin",
  });
  const apiTokens = useQuery({
    queryKey: ["account", "tokens"],
    queryFn: getApiTokens,
    enabled: Boolean(profile.data),
  });
  const invalidateAccounts = () => client.invalidateQueries({ queryKey: ["account"] });
  const invalidateApiTokens = () => {
    void client.invalidateQueries({ queryKey: ["account", "tokens"] });
    void client.invalidateQueries({ queryKey: ["account", "token-audit"] });
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
