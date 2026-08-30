import { describe, expect, it } from "vitest";

import { probeBulkActionNotice } from "@/features/probe/probe-bulk-action";

describe("probeBulkActionNotice", () => {
  it("reports complete, partial, and unavailable multi-server actions clearly", () => {
    expect(probeBulkActionNotice("Coda", 2, 2)).toMatchObject({
      tone: "success",
      message: "Svuotamento coda completato su 2 server.",
    });
    expect(probeBulkActionNotice("Storico", 1, 2)).toMatchObject({
      tone: "warning",
      message: "Svuotamento storico completato su 1 di 2 server. Controlla gli errori segnalati.",
    });
    expect(probeBulkActionNotice("Coda", 0, 0).tone).toBe("warning");
  });
});
