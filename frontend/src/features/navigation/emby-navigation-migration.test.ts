import { describe, expect, it } from "vitest";

import { embyWorkspaceNavigation } from "@/features/navigation/secondary-navigation";
import { normalizeTabOrder } from "@/features/navigation/tab-order";

describe("Emby workspace navigation migration", () => {
  it("maps a saved Operations tab position onto the unified Emby Live tab", () => {
    expect(
      normalizeTabOrder(embyWorkspaceNavigation, [
        { tab_key: "operations", position: 0 },
      ]),
    ).toContain("emby-live");
  });
});
