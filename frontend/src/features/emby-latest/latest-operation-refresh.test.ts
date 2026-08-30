import { describe, expect, it } from "vitest";

import {
  completedLatestOperations,
  hasActiveLatestWorkflow,
} from "@/features/emby-latest/latest-operation-refresh";
import type { Operation } from "@/features/operations/types";

function operation(
  id: string,
  kind: string,
  status: Operation["status"],
): Operation {
  return {
    id,
    kind,
    title: kind,
    summary: "",
    status,
    message: "",
    progress: 0,
    current: 0,
    total: null,
    details: {},
    error: null,
    started_at: "2026-08-14T10:00:00Z",
    updated_at: "2026-08-14T10:00:00Z",
    finished_at: status === "running" ? null : "2026-08-14T10:01:00Z",
  };
}

describe("latest operation refresh", () => {
  it("refreshes when a relevant operation becomes terminal", () => {
    expect(
      completedLatestOperations(
        [operation("one", "latest_refresh", "running")],
        [operation("one", "latest_refresh", "success")],
      ).map((item) => item.id),
    ).toEqual(["one"]);
  });

  it("does not refresh repeatedly or for unrelated operations", () => {
    const completed = operation("one", "workflow", "success");
    expect(completedLatestOperations([completed], [completed])).toEqual([]);
    expect(
      completedLatestOperations(
        [operation("two", "library_scan", "running")],
        [operation("two", "library_scan", "success")],
      ),
    ).toEqual([]);
  });

  it("recognizes only an active global workflow as blocking", () => {
    expect(
      hasActiveLatestWorkflow([
        operation("one", "workflow", "running"),
        operation("two", "latest_refresh", "running"),
      ]),
    ).toBe(true);
    expect(
      hasActiveLatestWorkflow([
        operation("one", "workflow", "success"),
        operation("two", "library_scan", "running"),
      ]),
    ).toBe(false);
  });
});
