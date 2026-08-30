import { describe, expect, it } from "vitest";

import {
  libraryLandingKey,
  libraryLandingOptions,
} from "@/features/user-settings/library-landing";

describe("library landing settings", () => {
  it("uses the shared Live TV key and server-specific keys for other libraries", () => {
    expect(libraryLandingKey({ id: "movies", collection_type: "movies" })).toBe("landing-movies");
    expect(libraryLandingKey({ id: "tv", collection_type: "livetv" })).toBe("landing-livetv");
  });

  it("preserves the media-specific choices from the legacy editor", () => {
    expect(libraryLandingOptions("tvshows")).toContainEqual({ value: "latest", label: "Ultimi episodi" });
    expect(libraryLandingOptions("livetv")).toContainEqual({ value: "guide", label: "Guida" });
  });
});
