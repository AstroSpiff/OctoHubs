import { describe, expect, it } from "vitest";

import { formatOperationTimestamp, isActiveOperation, operationCanStop, operationDetailTags, operationStatusLabel, operationStatusSeverity } from "@/features/operations/presentation";
import type { Operation } from "@/features/operations/types";

const workflow: Operation = {
  id: "workflow-1",
  kind: "workflow",
  title: "Workflow aggiornamento",
  summary: "smart",
  status: "running",
  message: "Analisi in corso",
  progress: 30,
  current: 1,
  total: 4,
  details: { can_stop: true, current_step_label: "Analisi" },
  error: null,
  started_at: "2026-08-12T09:00:00+00:00",
  updated_at: "2026-08-12T09:00:03+00:00",
  finished_at: null,
};

describe("operation presentation", () => {
  it("classifies active workflows and exposes their compact controls", () => {
    expect(isActiveOperation(workflow)).toBe(true);
    expect(operationCanStop(workflow)).toBe(true);
    expect(operationDetailTags(workflow)).toEqual([{ key: "current_step_label", value: "Analisi" }]);
  });

  it("uses clear Italian labels and keeps invalid timestamps readable", () => {
    expect(operationStatusLabel("interrupted")).toBe("Interrotta");
    expect(operationStatusSeverity("running")).toBe("info");
    expect(operationStatusSeverity("queued")).toBe("neutral");
    expect(formatOperationTimestamp("not-a-date")).toBe("not-a-date");
  });

  it("keeps the useful context of user operations compact", () => {
    expect(operationDetailTags({ ...workflow, kind: "clone", details: { source_username: "Anna", target_server: "Green" } })).toEqual([
      { key: "source_username", value: "Anna" },
      { key: "target_server", value: "Green" },
    ]);
  });
});
