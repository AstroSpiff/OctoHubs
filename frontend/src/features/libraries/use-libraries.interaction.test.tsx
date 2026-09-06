// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteLibraryScanHistoryJob,
  scanLibraryGroup,
  startLibraryWorkflow,
} from "@/features/libraries/api";
import { useLibraries } from "@/features/libraries/use-libraries";

vi.mock("@/features/libraries/api", () => ({
  deleteLibraryScanHistoryJob: vi.fn(),
  getActiveLibraryScans: vi.fn().mockResolvedValue({ active_scans: [] }),
  getActiveScanJobs: vi.fn().mockResolvedValue({ jobs: [] }),
  getGroupedLibraries: vi.fn().mockResolvedValue({ groups: [] }),
  getLibraryActionTargets: vi.fn().mockResolvedValue({ servers: [] }),
  getLibraryAssociations: vi.fn().mockResolvedValue({ associations: [] }),
  getLibraryScanHistory: vi.fn().mockResolvedValue({ jobs: [] }),
  resetLibraryScanHistory: vi.fn(),
  runLibraryMaintenance: vi.fn(),
  saveEmbyServerOrder: vi.fn(),
  saveLibraryAssociations: vi.fn(),
  saveLibraryGroupOrder: vi.fn(),
  scanLibraryGroup: vi.fn(),
  scanSingleLibrary: vi.fn(),
  startLibraryWorkflow: vi.fn(),
}));

vi.mock("@/features/libraries/use-libraries-realtime", () => ({ useLibrariesRealtime: vi.fn() }));

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void; reject: (reason: unknown) => void };

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((complete, fail) => { resolve = complete; reject = fail; });
  return { promise, reject, resolve };
}

let latest: ReturnType<typeof useLibraries> | undefined;

function Harness() {
  latest = useLibraries();
  return null;
}

describe("useLibraries keyed mutations", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>));
  });

  afterEach(() => {
    act(() => root.unmount());
    client.clear();
    container.remove();
    latest = undefined;
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("keeps concurrent group scan state attached to each group", async () => {
    const first = deferred<Awaited<ReturnType<typeof scanLibraryGroup>>>();
    const second = deferred<Awaited<ReturnType<typeof scanLibraryGroup>>>();
    vi.mocked(scanLibraryGroup).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const groupA = { group_name: "A", collection_type: "movies", servers: [], libraries: [] };
    const groupB = { group_name: "B", collection_type: "movies", servers: [], libraries: [] };

    act(() => {
      latest?.scan.mutate({ group: groupA, scanType: "content" });
      latest?.scan.mutate({ group: groupB, scanType: "content" });
    });
    expect(latest?.groupScanOperations.pendingKeys).toEqual(new Set(["A", "B"]));

    await act(async () => { second.resolve({ success: true }); await second.promise; });
    await act(async () => { first.reject(new Error("A non avviata")); await first.promise.catch(() => undefined); });

    expect(latest?.groupScanOperations.pendingKeys.size).toBe(0);
    expect(latest?.groupScanOperations.errors).toEqual({ A: "A non avviata" });
  });

  it("keeps concurrent history deletion state attached to each job", async () => {
    const first = deferred<Awaited<ReturnType<typeof deleteLibraryScanHistoryJob>>>();
    const second = deferred<Awaited<ReturnType<typeof deleteLibraryScanHistoryJob>>>();
    vi.mocked(deleteLibraryScanHistoryJob).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    act(() => {
      latest?.deleteHistoryJob.mutate("job-a");
      latest?.deleteHistoryJob.mutate("job-b");
    });
    expect(latest?.historyDeleteOperations.pendingKeys).toEqual(new Set(["job-a", "job-b"]));

    await act(async () => { second.resolve({ success: true, message: "ok" }); await second.promise; });
    await act(async () => { first.reject(new Error("Job A non eliminato")); await first.promise.catch(() => undefined); });

    expect(latest?.historyDeleteOperations.errors).toEqual({ "job-a": "Job A non eliminato" });
  });

  it.each([
    [{}, "workflow:all"],
    [{ server_id: "green" }, "workflow:server:green"],
  ] as const)("retains maintenance workflow errors for context %j", async (context, key) => {
    const operation = deferred<Awaited<ReturnType<typeof startLibraryWorkflow>>>();
    vi.mocked(startLibraryWorkflow).mockReturnValueOnce(operation.promise);

    act(() => latest?.workflow.mutate(context));
    expect(latest?.workflowMaintenanceOperations.pendingKeys).toEqual(new Set([key]));

    await act(async () => {
      operation.reject(new Error("Workflow non avviato"));
      await operation.promise.catch(() => undefined);
    });

    expect(latest?.workflowMaintenanceOperations.pendingKeys.size).toBe(0);
    expect(latest?.workflowMaintenanceOperations.errors).toEqual({
      [key]: "Workflow non avviato",
    });
  });
});
