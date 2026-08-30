import { describe, expect, it } from "vitest";

import { moveTab, moveTabAfter, moveTabBefore, normalizeTabOrder, serializeTabOrder } from "@/features/navigation/tab-order";

const tabs = [
  { id: "operations", label: "Operazioni", legacyIds: ["actions"] },
  { id: "guard", label: "Transcode Guard" },
  { id: "users", label: "Utenti" },
] as const;

describe("tab order", () => {
  it("keeps a saved legacy order and appends newly introduced tabs", () => {
    expect(normalizeTabOrder(tabs, [
      { tab_key: "users", position: 0 },
      { tab_key: "actions", position: 1 },
      { tab_key: "unknown", position: 2 },
    ])).toEqual(["users", "operations", "guard"]);
  });

  it("moves tabs without losing the complete sequence", () => {
    expect(moveTab(["operations", "guard", "users"], "guard", -1)).toEqual(["guard", "operations", "users"]);
    expect(moveTabBefore(["operations", "guard", "users"], "users", "guard")).toEqual(["operations", "users", "guard"]);
    expect(moveTabAfter(["operations", "guard", "users"], "operations", "users")).toEqual(["guard", "users", "operations"]);
  });

  it("serializes current identifiers for future saves", () => {
    expect(serializeTabOrder("emby", ["users", "operations"])).toEqual({
      page: "emby",
      order: [
        { tab_key: "users", position: 0 },
        { tab_key: "operations", position: 1 },
      ],
    });
  });
});
