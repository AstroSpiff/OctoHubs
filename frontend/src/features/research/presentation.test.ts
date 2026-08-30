import { describe, expect, it } from "vitest";

import { displayFileSize, displayMediaType, formatResearchDate, magnetExportLink, resultSortBySeeders, tmdbPosterUrl, torrentDownloadLink } from "@/features/research/presentation";

describe("research presentation", () => {
  it("formats result properties without changing backend rows", () => {
    const results = [{ title: "Low", seeders: 2 }, { title: "High", seeders: 12 }];
    expect(resultSortBySeeders(results).map((result) => result.title)).toEqual(["High", "Low"]);
    expect(results.map((result) => result.title)).toEqual(["Low", "High"]);
    expect(displayFileSize(1.25)).toBe("1.25 GB");
    expect(displayMediaType("tv")).toBe("Serie TV");
    expect(tmdbPosterUrl("/cover.jpg")).toBe("https://image.tmdb.org/t/p/w154/cover.jpg");
    expect(tmdbPosterUrl("https://example.test/cover.jpg")).toBe("https://example.test/cover.jpg");
    expect(torrentDownloadLink({ magnet: "magnet:?xt=urn:btih:hash", torrent: "https://example.test/file.torrent" })).toBe("https://example.test/file.torrent");
    expect(torrentDownloadLink({ link: "magnet:?xt=urn:btih:hash" })).toBeNull();
    expect(magnetExportLink({ magnetUri: "magnet:?xt=urn:btih:hash" })).toBe("magnet:?xt=urn:btih:hash");
    expect(magnetExportLink({ magnet: "https://example.test/file.torrent" })).toBeNull();
  });

  it("keeps diagnostic timestamps readable through seconds", () => {
    expect(formatResearchDate("2026-08-12T14:43:05+02:00")).toMatch(
      /12\/08\/2026, 14:43:05/,
    );
  });
});
