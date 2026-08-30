import { describe, expect, it } from "vitest";

import { collectionListsFromOperation } from "@/features/collections/api";
import type { Operation } from "@/features/operations/types";

function operation(
  status: Operation["status"],
  result: Operation["result"],
): Operation {
  return {
    id: "operation-1",
    kind: "collections_trakt_lists",
    title: "Aggiornamento Liste Trakt",
    summary: "Collezioni",
    status,
    message: "Operazione conclusa",
    progress: 100,
    current: 1,
    total: 1,
    details: {},
    result,
    error: status === "error" ? "Servizio non raggiungibile" : null,
    started_at: "2026-08-12T09:00:00+00:00",
    updated_at: "2026-08-12T09:00:01+00:00",
    finished_at: "2026-08-12T09:00:01+00:00",
  };
}

describe("collection operation results", () => {
  it("uses the list payload stored by a completed background operation", () => {
    expect(
      collectionListsFromOperation(
        operation("success", { lists: [{ name: "Preferiti" }] }),
        "Trakt",
      ),
    ).toEqual({ success: true, lists: [{ name: "Preferiti" }] });
  });

  it("surfaces a terminal operation error instead of an empty list", () => {
    expect(() =>
      collectionListsFromOperation(operation("error", null), "MDBList"),
    ).toThrow("Servizio non raggiungibile");
  });
});
