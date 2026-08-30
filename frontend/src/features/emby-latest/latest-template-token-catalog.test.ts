import { describe, expect, it } from "vitest";

import { latestTemplateTokens } from "@/features/emby-latest/latest-template-token-catalog";

describe("latestTemplateTokens", () => {
  it("keeps the complete legacy token families available to the React editor", () => {
    expect(latestTemplateTokens).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ token: "{title}", group: "Identità" }),
        expect.objectContaining({ token: "{best_audio_details}" }),
        expect.objectContaining({ token: "{jellyseerr_requested_by}" }),
        expect.objectContaining({ token: "{tmdb_backdrop_url}" }),
        expect.objectContaining({ token: "{% for v in versions %}" }),
      ]),
    );
  });
});
