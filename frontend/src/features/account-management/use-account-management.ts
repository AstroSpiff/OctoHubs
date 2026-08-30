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

function useApiTokenAudit(filters: ApiTokenAuditFilters, enabled: boolean) {
  return useQuery({
    queryKey: ["account", "token-audit", filters.tokenId || null, filters.result || null, filters.apiVersion || null],
    queryFn: () => getApiTokenAudit(filters),
    enabled,
  });
}

function useAccountManagement() {
  const client = useQueryClient();
  const profile = useQuery({ queryKey: ["account", "me"], queryFn: getCurrentAccount });
  const accounts = useQuery({
    queryKey: ["account", "list"],
    queryFn: getAccounts,
    enabled: profile.data?.role === "admin",
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
  const updatePassword = useMutation({ mutationFn: updateCurrentPassword });
  const createToken = useMutation({
    mutationFn: createApiToken,
    onSuccess: invalidateApiTokens,
  });
  const revokeToken = useMutation({
    mutationFn: revokeApiToken,
    onSuccess: invalidateApiTokens,
  });
  const rotateToken = useMutation({
    mutationFn: rotateApiToken,
    onSuccess: invalidateApiTokens,
  });
  const create = useMutation({
    mutationFn: createAccount,
    onSuccess: invalidateAccounts,
  });
  const update = useMutation({
    mutationFn: ({ accountId, input }: { accountId: number; input: UpdateOctoHubsAccountInput }) => updateAccount(accountId, input),
    onSuccess: invalidateAccounts,
  });
  const remove = useMutation({
    mutationFn: deleteAccount,
    onSuccess: invalidateAccounts,
  });

  return {
    accounts,
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
    createApiToken: (input: CreateApiTokenInput) => createToken.mutateAsync(input),
    exportApiTokenAudit,
  };
}

export { useAccountManagement, useApiTokenAudit };
