import { describe, expect, it } from "vitest";

import { batchSendNotice } from "@/features/research/batch-send-outcome";

describe("Prowlarr batch outcomes", () => {
  it("reports a mixed HTTP-200 result as a warning", () => {
    expect(batchSendNotice({ sent: 1, failed: 1, total: 2 }, 2)).toEqual({
      message: "1/2 risultati inviati tramite Prowlarr; 1 non inviati.",
      tone: "warning",
    });
  });
});
