import { describe, expect, it } from "vitest";

import {
  collectionImageMaxBytes,
  collectionMediaFileError,
} from "@/features/collections/collection-media-file";

describe("collectionMediaFileError", () => {
  it("accepts the image formats allowed by the legacy collection editor", () => {
    expect(
      collectionMediaFileError(
        { size: 512, type: "image/webp" },
        "Poster",
      ),
    ).toBeNull();
  });

  it("rejects files larger than 5 MB", () => {
    expect(
      collectionMediaFileError(
        { size: collectionImageMaxBytes + 1, type: "image/jpeg" },
        "Sfondo",
      ),
    ).toBe("Sfondo troppo grande. Limite 5 MB.");
  });

  it("rejects unsupported image formats", () => {
    expect(
      collectionMediaFileError(
        { size: 512, type: "image/gif" },
        "Poster",
      ),
    ).toBe("Formato poster non supportato.");
  });

  it("rejects active SVG content", () => {
    expect(
      collectionMediaFileError(
        { size: 512, type: "image/svg+xml" },
        "Poster",
      ),
    ).toBe("Formato poster non supportato.");
  });
});
