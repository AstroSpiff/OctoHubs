import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import {
  accountQueryKeys,
  synchronizeAccountQueryCacheOwner,
} from "@/features/account-management/account-query-cache";
import { accountQueryOwnershipViolations } from "@/features/account-management/account-query-cache-source-gate";
import type { ApiTokenAuditFilters } from "@/features/account-management/types";

const filters = { tokenId: 1, result: "allowed", apiVersion: "v1" } satisfies ApiTokenAuditFilters;
const families = [
  ["profile", (owner: number) => accountQueryKeys.profile(owner)],
  ["accounts", (owner: number) => accountQueryKeys.accounts(owner)],
  ["tokens", (owner: number) => accountQueryKeys.tokens(owner)],
  ["token audit", (owner: number) => accountQueryKeys.tokenAudit(owner, filters)],
] as const;

describe("account-owned QueryCache", () => {
  it.each(families)("fences cached %s data on a same-capability A to B change", (_family, key) => {
    const client = queryClient();
    client.setQueryData(key(1), { owner: "A" });
    client.setQueryData(key(2), { owner: "B" });

    const observer = new QueryObserver(client, {
      queryKey: key(2),
      queryFn: async () => ({ owner: "B-fetched" }),
      enabled: false,
    });
    synchronizeAccountQueryCacheOwner(client, 2);

    expect(observer.getCurrentResult().data).toEqual({ owner: "B" });
    expect(client.getQueryData(key(1))).toBeUndefined();
    expect(client.getQueryData(key(2))).toEqual({ owner: "B" });
    observer.destroy();
  });

  it.each(families)("cancels and fences a late %s response from A", async (_family, key) => {
    const client = queryClient();
    let resolveA!: (value: { owner: string }) => void;
    const responseA = new Promise<{ owner: string }>((resolve) => {
      resolveA = resolve;
    });
    const fetchA = client.fetchQuery({
      queryKey: key(1),
      queryFn: () => responseA,
    });
    await Promise.resolve();

    synchronizeAccountQueryCacheOwner(client, 2);
    resolveA({ owner: "A-late" });
    await fetchA.catch(() => undefined);

    expect(client.getQueryData(key(1))).toBeUndefined();
    expect(client.getQueryData(key(2))).toBeUndefined();
  });

  it.each(families)("does not restore A when B's %s fetch rejects", async (_family, key) => {
    const client = queryClient();
    client.setQueryData(key(1), { owner: "A" });
    synchronizeAccountQueryCacheOwner(client, 2);

    await expect(client.fetchQuery({
      queryKey: key(2),
      queryFn: async () => { throw new Error("B unavailable"); },
    })).rejects.toThrow("B unavailable");

    expect(client.getQueryData(key(1))).toBeUndefined();
    expect(client.getQueryData(key(2))).toBeUndefined();
  });

  it("cancels active account requests and removes legacy unowned keys", async () => {
    const client = queryClient();
    const abort = vi.fn();
    void client.fetchQuery({
      queryKey: accountQueryKeys.tokens(1),
      queryFn: ({ signal }) => new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => {
          abort();
          reject(signal.reason);
        });
      }),
    }).catch(() => undefined);
    client.setQueryData(["account", "me"], { owner: "legacy" });
    await Promise.resolve();

    synchronizeAccountQueryCacheOwner(client, 2);

    expect(abort).toHaveBeenCalledOnce();
    expect(client.getQueryData(["account", "me"])).toBeUndefined();
  });

  it("requires every account-management query to use the owner-aware key factory", () => {
    const sourceRoot = fileURLToPath(new URL("./", import.meta.url));
    const violations = collectSourceFiles(sourceRoot).flatMap((path) =>
      accountQueryOwnershipViolations(
        readFileSync(path, "utf8"),
        path.slice(sourceRoot.length),
      ),
    );

    expect(violations).toEqual([]);
  });

  it("rejects a new global account query key", () => {
    const source = `const query = useQuery({ queryKey: ["account", "me"], queryFn: load });`;
    expect(accountQueryOwnershipViolations(source, "unsafe.ts")).toHaveLength(1);
  });
});

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function collectSourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return collectSourceFiles(path);
    return /\.(?:ts|tsx)$/.test(entry.name) && !entry.name.includes(".test.")
      ? [path]
      : [];
  });
}
