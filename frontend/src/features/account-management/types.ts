import type { NavigationPreferences } from "@/features/navigation/navigation-preferences";

type AccountRole = "admin" | "user" | "viewer";

type OctoHubsAccount = {
  id: number;
  username: string;
  email: string;
  role: AccountRole;
  is_active: boolean;
  created_at: string | null;
  last_login: string | null;
};

type CurrentOctoHubsAccount = OctoHubsAccount & {
  preferences: NavigationPreferences;
};

type CreateOctoHubsAccountInput = {
  username: string;
  email: string;
  password: string;
  role: AccountRole;
};

type UpdateOctoHubsAccountInput = {
  email?: string;
  role?: AccountRole;
  is_active?: boolean;
  password?: string;
};

type ApiTokenScope =
  | "read:status"
  | "read:account"
  | "read:servers"
  | "read:streams"
  | "read:users"
  | "read:collections"
  | "read:libraries"
  | "read:research"
  | "read:publications"
  | "read:configuration"
  | "write:configuration"
  | "write:account"
  | "manage:tokens"
  | "admin:accounts"
  | "read:event_bridge"
  | "write:event_bridge"
  | "write:transcode_guard"
  | "write:users"
  | "write:collections"
  | "write:libraries"
  | "write:research"
  | "write:publications"
  | "run:operations"
  | "admin:all";

type ApiTokenPermissionProfileId = "read_only" | "operator" | "administrator";

type ApiTokenPermissionProfile = {
  id: ApiTokenPermissionProfileId;
  scopes: ApiTokenScope[];
};

type ApiToken = {
  id: number;
  name: string;
  prefix: string;
  scopes: ApiTokenScope[];
  permission_profile: ApiTokenPermissionProfileId | null;
  is_active: boolean;
  is_expired: boolean;
  status: "active" | "expired" | "revoked";
  created_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  expires_at: string | null;
  last_action: {
    action: string;
    at: string | null;
    method: string;
    path: string;
    required_scope: ApiTokenScope | string;
    result: string;
  } | null;
};

type ApiTokenList = {
  available_permission_profiles: ApiTokenPermissionProfile[];
  tokens: ApiToken[];
};

type CreateApiTokenInput = {
  name: string;
  permissionProfile: ApiTokenPermissionProfileId;
  expiresInDays: number | null;
};

type CreatedApiToken = {
  token: ApiToken;
  secret: string;
  message: string;
};

type ApiTokenAuditResult = "allowed" | "denied";
type ApiTokenAuditVersion = "v1" | "legacy";

type ApiTokenAuditFilters = {
  tokenId?: number;
  result?: ApiTokenAuditResult;
  apiVersion?: ApiTokenAuditVersion;
};

type ApiTokenAuditEvent = {
  id: number;
  at: string | null;
  token_id: number;
  token_name: string;
  token_prefix: string;
  action: string;
  result: ApiTokenAuditResult;
  required_scope: ApiTokenScope | string;
  method: string;
  path: string;
  api_version: ApiTokenAuditVersion | "unknown";
  ip_address: string;
  user_agent: string;
};

type ApiTokenAuditList = {
  events: ApiTokenAuditEvent[];
  filters: {
    token_id: number | null;
    result: ApiTokenAuditResult | null;
    api_version: ApiTokenAuditVersion | null;
    limit: number;
  };
};

export type {
  AccountRole,
  ApiToken,
  ApiTokenAuditEvent,
  ApiTokenAuditFilters,
  ApiTokenAuditList,
  ApiTokenAuditResult,
  ApiTokenAuditVersion,
  ApiTokenList,
  ApiTokenPermissionProfile,
  ApiTokenPermissionProfileId,
  ApiTokenScope,
  CreateOctoHubsAccountInput,
  CreateApiTokenInput,
  CreatedApiToken,
  CurrentOctoHubsAccount,
  OctoHubsAccount,
  UpdateOctoHubsAccountInput,
};
