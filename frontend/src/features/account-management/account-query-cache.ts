import type { Query, QueryClient, QueryKey } from "@tanstack/react-query";

import type { ApiTokenAuditFilters } from "@/features/account-management/types";

const ACCOUNT_QUERY_ROOT = "account";
const ACCOUNT_QUERY_OWNER = "owner";

type AccountQueryOwner = number;
type AccountQueryFamily = "me" | "list" | "tokens" | "token-audit";

function accountQueryPrefix(owner: AccountQueryOwner): QueryKey {
  return [ACCOUNT_QUERY_ROOT, ACCOUNT_QUERY_OWNER, owner];
}

function accountQueryKey(
  owner: AccountQueryOwner,
  family: AccountQueryFamily,
  ...parts: unknown[]
): QueryKey {
  return [...accountQueryPrefix(owner), family, ...parts];
}

const accountQueryKeys = {
  all: accountQueryPrefix,
  profile: (owner: AccountQueryOwner) => accountQueryKey(owner, "me"),
  accounts: (owner: AccountQueryOwner) => accountQueryKey(owner, "list"),
  tokens: (owner: AccountQueryOwner) => accountQueryKey(owner, "tokens"),
  tokenAudits: (owner: AccountQueryOwner) =>
    accountQueryKey(owner, "token-audit"),
  tokenAudit: (owner: AccountQueryOwner, filters: ApiTokenAuditFilters) =>
    accountQueryKey(
      owner,
      "token-audit",
      filters.tokenId || null,
      filters.result || null,
      filters.apiVersion || null,
    ),
};

function queryIsOwnedByAnotherAccount(
  query: Query,
  currentOwner: AccountQueryOwner | null,
) {
  const [root, marker, owner] = query.queryKey;
  if (root !== ACCOUNT_QUERY_ROOT) return false;
  return currentOwner == null
    || marker !== ACCOUNT_QUERY_OWNER
    || owner !== currentOwner;
}

function synchronizeAccountQueryCacheOwner(
  client: QueryClient,
  currentOwner: AccountQueryOwner | null,
) {
  const predicate = (query: Query) =>
    queryIsOwnedByAnotherAccount(query, currentOwner);
  // cancelQueries invokes each query cancellation synchronously. The returned
  // promise only represents notification completion; removal fences even a
  // query function that ignores AbortSignal before another owner can observe it.
  void client.cancelQueries({ predicate });
  client.removeQueries({ predicate });
}

export {
  ACCOUNT_QUERY_OWNER,
  ACCOUNT_QUERY_ROOT,
  accountQueryKeys,
  queryIsOwnedByAnotherAccount,
  synchronizeAccountQueryCacheOwner,
};
export type { AccountQueryFamily, AccountQueryOwner };
