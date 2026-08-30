import { describe, expect, it } from "vitest";

import {
  copyLatestRuleInput,
  emptyLatestRuleInput,
  latestRuleInputMatches,
} from "@/features/emby-latest/latest-rule-draft";

describe("latest rule draft", () => {
  it("starts a new rule with no implicit destination", () => {
    expect(emptyLatestRuleInput()).toEqual({
      name: "",
      server_ids: [],
      preset_id: "",
      telegram_config_id: "",
    });
  });

  it("compares server selections as a set and preserves draft isolation", () => {
    const original = {
      id: "public-movies",
      name: "Film pubblici",
      server_ids: ["green", "purple"],
      preset_id: "movies",
      telegram_config_id: "public",
    };
    const copied = copyLatestRuleInput(original);

    copied.server_ids.pop();
    expect(original.server_ids).toEqual(["green", "purple"]);
    expect(
      latestRuleInputMatches(original, {
        ...original,
        server_ids: ["purple", "green"],
      }),
    ).toBe(true);
  });
});
