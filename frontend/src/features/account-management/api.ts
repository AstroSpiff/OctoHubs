import { request, requestBlob } from "@/lib/http";

import type {
  ApiTokenList,
  ApiTokenAuditFilters,
  ApiTokenAuditList,
  CreateOctoHubsAccountInput,
  CreateApiTokenInput,
  CreatedApiToken,
  CurrentOctoHubsAccount,
  OctoHubsAccount,
  UpdateOctoHubsAccountInput,
} from "@/features/account-management/types";

async function getCurrentAccount(): Promise<CurrentOctoHubsAccount> {
  return (await request<{ account: CurrentOctoHubsAccount }>("/api/v1/account/me")).account;
}

async function updateCurrentPassword(input: { currentPassword: string; newPassword: string }) {
  return request<{ success: boolean; message: string }>("/api/v1/account/me/password", {
    method: "PUT",
    body: JSON.stringify({ current_password: input.currentPassword, new_password: input.newPassword }),
  });
}

async function getAccounts(): Promise<OctoHubsAccount[]> {
  return (await request<{ accounts: OctoHubsAccount[] }>("/api/v1/admin/accounts")).accounts;
}

async function createAccount(input: CreateOctoHubsAccountInput): Promise<OctoHubsAccount> {
  return (await request<{ success: boolean; account: OctoHubsAccount }>("/api/v1/admin/accounts", {
    method: "POST",
    body: JSON.stringify(input),
  })).account;
}

async function updateAccount(accountId: number, input: UpdateOctoHubsAccountInput): Promise<OctoHubsAccount> {
  return (await request<{ success: boolean; account: OctoHubsAccount }>(`/api/v1/admin/accounts/${accountId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  })).account;
}

async function deleteAccount(accountId: number): Promise<void> {
  await request<{ success: boolean }>(`/api/v1/admin/accounts/${accountId}`, { method: "DELETE" });
}

async function getApiTokens(): Promise<ApiTokenList> {
  return request<ApiTokenList>("/api/v1/account/tokens");
}

async function createApiToken(input: CreateApiTokenInput): Promise<CreatedApiToken> {
  return request<{ success: boolean } & CreatedApiToken>("/api/v1/account/tokens", {
    method: "POST",
    body: JSON.stringify({ name: input.name, permission_profile: input.permissionProfile, expires_in_days: input.expiresInDays }),
  });
}

async function revokeApiToken(tokenId: number): Promise<void> {
  await request<{ success: boolean }>(`/api/v1/account/tokens/${tokenId}`, { method: "DELETE" });
}

async function rotateApiToken(tokenId: number): Promise<CreatedApiToken> {
  return request<{ success: boolean } & CreatedApiToken>(`/api/v1/account/tokens/${tokenId}/rotate`, { method: "POST" });
}

function auditQuery(filters: ApiTokenAuditFilters) {
  const query = new URLSearchParams();
  if (filters.tokenId) query.set("token_id", String(filters.tokenId));
  if (filters.result) query.set("result", filters.result);
  if (filters.apiVersion) query.set("api_version", filters.apiVersion);
  return query.toString();
}

async function getApiTokenAudit(filters: ApiTokenAuditFilters = {}): Promise<ApiTokenAuditList> {
  const query = auditQuery(filters);
  return request<ApiTokenAuditList>(`/api/v1/account/tokens/audit${query ? `?${query}` : ""}`);
}

async function exportApiTokenAudit(filters: ApiTokenAuditFilters = {}): Promise<Blob> {
  const query = auditQuery(filters);
  return requestBlob(`/api/v1/account/tokens/audit/export${query ? `?${query}` : ""}`);
}

export {
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
};
