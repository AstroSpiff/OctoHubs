import { describe, expect, it } from "vitest";

import { latestRefreshPresentation } from "@/features/emby-latest/latest-progress-presentation";

describe("latestRefreshPresentation", () => {
  it("describes collection progress with a precise count", () => {
    expect(
      latestRefreshPresentation({
        state: "collecting",
        total: 80,
        completed: 20,
        message: "Lettura librerie",
      }),
    ).toMatchObject({
      label: "Raccolta da Emby",
      message: "Lettura librerie",
      completed: 20,
      total: 80,
      percent: 25,
    });
  });

  it("keeps a useful indeterminate state before totals are known", () => {
    expect(latestRefreshPresentation({ state: "enriching" })).toMatchObject({
      label: "Arricchimento dati",
      message: "Aggiornamento in corso",
      percent: undefined,
    });
  });
});
