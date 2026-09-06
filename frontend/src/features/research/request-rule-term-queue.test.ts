import { describe, expect, it, vi } from "vitest";

import { createRequestRuleTermQueue } from "@/features/research/request-rule-term-queue";
import type { RequestSearchRule } from "@/features/research/types";

const baseline: RequestSearchRule = {
  request_id: 7,
  enabled: true,
  query_terms: "",
  filter_terms: "",
  exclude_terms: "",
  use_original_title: true,
  use_alt_titles_original: true,
  use_alt_titles_language: false,
  alt_titles_language: "",
  year_variance: 0,
};

describe("request rule term queue", () => {
  it("serializes additions and derives each payload from the last saved rule", async () => {
    let releaseFirst!: () => void;
    const firstSave = new Promise<void>((resolve) => { releaseFirst = resolve; });
    const save = vi.fn()
      .mockImplementationOnce(() => firstSave)
      .mockResolvedValueOnce(undefined);
    const queue = createRequestRuleTermQueue(save);

    const first = queue.enqueue(7, baseline, "alpha", "query_terms");
    const second = queue.enqueue(7, baseline, "beta", "query_terms");
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));

    releaseFirst();
    await Promise.all([first, second]);
    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[1]?.[0].query_terms).toBe("alpha, beta");
  });

  it("continues from the baseline after a failed predecessor", async () => {
    const save = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(undefined);
    const queue = createRequestRuleTermQueue(save);
    const failed = queue.enqueue(7, baseline, "alpha", "query_terms");
    const recovered = queue.enqueue(7, baseline, "beta", "query_terms");

    await expect(failed).rejects.toThrow("offline");
    await expect(recovered).resolves.toContain("beta");
    expect(save.mock.calls[1]?.[0].query_terms).toBe("beta");
  });

  it("uses a refreshed baseline after the previous queue has drained", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const queue = createRequestRuleTermQueue(save);

    await queue.enqueue(7, baseline, "alpha", "query_terms");
    await Promise.resolve();
    const refreshed = { ...baseline, query_terms: "external" };
    await queue.enqueue(7, refreshed, "beta", "query_terms");

    expect(save.mock.calls[1]?.[0].query_terms).toBe("external, beta");
  });

  it("retains the saved rule until a delayed overview refresh arrives", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const queue = createRequestRuleTermQueue(save);

    await queue.enqueue(7, baseline, "alpha", "query_terms");
    await Promise.resolve();
    await queue.enqueue(7, baseline, "beta", "query_terms");

    expect(save.mock.calls[1]?.[0].query_terms).toBe("alpha, beta");
  });
});
