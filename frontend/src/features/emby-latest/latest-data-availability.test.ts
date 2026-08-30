import { describe, expect, it } from "vitest";

import {
  formatLatestVerificationValue,
  latestVerification,
} from "@/features/emby-latest/latest-data-availability";
import type { LatestItem } from "@/features/emby-latest/types";

describe("latest verification", () => {
  it("reports human-readable fields and omits expected MediaInfo absences", () => {
    const item: LatestItem = {
      title: "Titolo di prova",
      tmdb_id: "42",
      changes: [
        {
          path: "/media/Test_File.mkv",
          mediainfo_available: true,
          audio_details: "Italiano AAC 5.1",
        },
      ],
    };

    const verification = latestVerification(item, "movie");
    const availableFields = verification.common.available.map((field) => field.field);
    const missingFields = verification.files[0]?.missing.map((field) => field.field);

    expect(availableFields).toContain("title");
    expect(availableFields).toContain("tmdb_id");
    expect(verification.common.available.find((field) => field.field === "tmdb_id"))
      .toMatchObject({ label: "TMDB ID", source: "TMDB" });
    expect(verification.files[0]?.label).toBe("File 1 · Test File");
    expect(missingFields).not.toContain("quality");
    expect(missingFields).not.toContain("audio_ita");
  });

  it("separates the fields actually added by enrichment", () => {
    const before: LatestItem = { title: "Titolo" };
    const after: LatestItem = { title: "Titolo", imdb_id: "tt123" };

    const verification = latestVerification(after, "movie", before);

    expect(verification.common.added).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ field: "imdb_id", source: "MDBList / OMDB" }),
      ]),
    );
    expect(verification.common.added.map((field) => field.field)).not.toContain(
      "title",
    );
  });

  it("formats values without exposing raw URLs", () => {
    expect(
      formatLatestVerificationValue("tmdb_poster_url", "https://image.tmdb.org/a.jpg"),
    ).toBe("Disponibile");
    expect(formatLatestVerificationValue("runtime_minutes", 125)).toBe("2h 5m");
    expect(formatLatestVerificationValue("jellyseerr_requested", false)).toBe("No");
  });
});
