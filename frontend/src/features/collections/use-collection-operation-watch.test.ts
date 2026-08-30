import { describe, expect, it } from "vitest";

import {
  completedCollectionOperations,
  type TrackedOperation,
} from "@/features/collections/use-collection-operation-watch";
import type { Operation } from "@/features/operations/types";

const operation = (id: string, status: Operation["status"]): Operation => ({
  id,
  kind: "collection_sync",
  title: "Sincronizzazione collezione",
  summary: "collection-1",
  status,
  message: "Stato",
  progress: 20,
  current: 0,
  total: 1,
  details: {},
  error: null,
  started_at: "2026-08-12T10:00:00+00:00",
  updated_at: "2026-08-12T10:00:01+00:00",
  finished_at: status === "running" ? null : "2026-08-12T10:00:02+00:00",
});

describe("collection operation watch", () => {
  it("keeps active operations pending and refreshes only after they settle", () => {
    const tracked: TrackedOperation[] = [
      { operationId: "active", type: "collection", collectionId: "collection-1" },
      { operationId: "done", type: "all" },
    ];

    expect(
      completedCollectionOperations(tracked, [
        operation("active", "running"),
        operation("done", "success"),
      ]),
    ).toEqual([{ operationId: "done", type: "all" }]);
  });
});
