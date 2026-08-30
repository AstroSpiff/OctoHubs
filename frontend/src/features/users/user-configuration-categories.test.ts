import { describe, expect, it } from "vitest";

import { defaultUserConfigurationCategoryIds, userConfigurationCategories } from "@/features/users/user-configuration-categories";

describe("user configuration categories", () => {
  it("keeps the safe legacy defaults and leaves parental restrictions opt-in", () => {
    expect(defaultUserConfigurationCategoryIds).toContain("profile_pin");
    expect(defaultUserConfigurationCategoryIds).not.toContain("parental");
    expect(userConfigurationCategories).toHaveLength(8);
  });
});
