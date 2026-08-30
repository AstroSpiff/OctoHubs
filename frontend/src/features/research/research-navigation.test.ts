import { describe, expect, it } from "vitest";

import {
  researchPath,
  researchTabAtOffset,
  researchTabFromHash,
  researchTabFromRoute,
} from "@/features/research/research-navigation";

describe("research navigation", () => {
  it("uses a stable default tab and cycles keyboard navigation", () => {
    expect(researchTabFromHash("#rules")).toBe("rules");
    expect(researchTabFromHash("#independent-search")).toBe("independent");
    expect(researchTabFromHash("#scan")).toBe("summary");
    expect(researchTabFromHash("#missing")).toBe("independent");
    expect(researchTabFromRoute("summary")).toBe("summary");
    expect(researchTabFromRoute("requests")).toBe("requests");
    expect(researchTabFromRoute("missing")).toBe("independent");
    expect(researchPath("independent")).toBe("/research/independent");
    expect(researchPath("rules")).toBe("/research/rules");
    expect(researchPath("requests")).toBe("/research/requests");
    expect(researchTabAtOffset("requests", 1)).toBe("independent");
  });
});
