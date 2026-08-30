import { describe, expect, it } from "vitest";

import { searchProgressMessage } from "@/features/research/search-progress";

describe("searchProgressMessage", () => {
  it("reports the latest live query before the total is known", () => {
    expect(
      searchProgressMessage({
        completedQueries: 0,
        latestQuery: "Titolo originale 2026",
        latestIndexer: "Prowlarr",
      }),
    ).toBe("Ricerca in corso · Titolo originale 2026 · Prowlarr");
  });

  it("reports completed queries without exceeding the known total", () => {
    expect(
      searchProgressMessage({
        completedQueries: 7,
        totalQueries: 5,
        latestIndexer: "Jackett",
      }),
    ).toBe("Query completate 5 di 5 · Jackett");
  });
});
