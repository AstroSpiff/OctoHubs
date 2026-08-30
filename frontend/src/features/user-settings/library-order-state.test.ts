import { describe, expect, it } from "vitest";

import {
  moveLibraryOrderItem,
  normalizeLibraryOrder,
  removeLibraryOrderItem,
} from "@/features/user-settings/library-order-state";

describe("library order state", () => {
  it("keeps saved IDs and moves only valid positions", () => {
    const order = normalizeLibraryOrder(["movies", "shows", "music"]);

    expect(moveLibraryOrderItem(order, 1, -1)).toEqual(["shows", "movies", "music"]);
    expect(moveLibraryOrderItem(order, 0, -1)).toEqual(order);
  });

  it("removes one ordered library without changing the remaining order", () => {
    expect(removeLibraryOrderItem(["movies", "shows", "music"], 1)).toEqual(["movies", "music"]);
  });
});
