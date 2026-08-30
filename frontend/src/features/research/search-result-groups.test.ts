import { describe, expect, it } from "vitest";

import {
  filterBucketResults,
  groupIndexedResultsByResolution,
  groupSearchResultsByResolution,
  groupSearchResultsBySeason,
  searchResultEntries,
} from "@/features/research/search-result-groups";

describe("search result groups", () => {
  const results = [
    { title: "Film 1080p HDR", resolution: "1080p" },
    { title: "Film 2160p DV", resolution_bucket: "2160p" },
    { title: "Sorgente senza risoluzione" },
  ];

  it("groups results in the fixed resolution order without changing rows", () => {
    const groups = groupSearchResultsByResolution(results);
    expect(groups.map((group) => group.key)).toEqual(["2160p", "1080p", "other"]);
    expect(groups[0].items[0]).toMatchObject({ index: 1, result: results[1] });
  });

  it("filters a bucket with every comma-separated term", () => {
    const group = groupSearchResultsByResolution(results).find((entry) => entry.key === "1080p");
    expect(filterBucketResults(group?.items || [], "film, hdr")).toHaveLength(1);
    expect(filterBucketResults(group?.items || [], "film, dv")).toHaveLength(0);
  });

  it("keeps duplicate sources selectable and searchable under their canonical result", () => {
    const withDuplicate = [{
      title: "Film principale",
      resolution: "1080p",
      duplicates: [{ title: "Film altra fonte", indexer: "Jackett" }],
    }];
    const group = groupSearchResultsByResolution(withDuplicate)[0];

    expect(group.items[0].duplicates).toMatchObject([
      { key: "0:duplicate:0", result: withDuplicate[0].duplicates?.[0] },
    ]);
    expect(filterBucketResults(group.items, "altra fonte")).toHaveLength(1);
    expect(searchResultEntries(withDuplicate).map((entry) => entry.key)).toEqual([
      "0",
      "0:duplicate:0",
    ]);
  });

  it("keeps TV result keys stable while grouping seasons before resolutions", () => {
    const results = [
      { title: "Serie S02E01", season_number: 2, resolution: "1080p" },
      { title: "Serie S01E02", episode_code: "S01E02", resolution: "2160p" },
      { title: "Speciale", season_label: "S00", resolution: "720p" },
      { title: "Senza stagione", resolution: "480p" },
    ];
    const groups = groupSearchResultsBySeason(results);

    expect(groups.map((group) => group.label)).toEqual([
      "Speciali",
      "Stagione 1",
      "Stagione 2",
      "Tutti i risultati",
    ]);
    expect(groups[1].items[0].key).toBe("1");
    expect(groupIndexedResultsByResolution(groups[1].items)[0].key).toBe("2160p");
  });
});
