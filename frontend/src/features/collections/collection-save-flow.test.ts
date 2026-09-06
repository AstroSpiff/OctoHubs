import { describe, expect, it, vi } from "vitest";

import { saveCollectionWithImages } from "@/features/collections/collection-save-flow";
import type {
  CollectionEditorInput,
  EmbyCollection,
} from "@/features/collections/types";

const newCollectionInput: CollectionEditorInput = {
  name: "Cinema",
  sort_name: "Cinema",
  source_type: "trakt",
  source_value: "cinema",
  source_origin: "manual",
  server_ids: ["green"],
  refresh_metadata: false,
  use_source_description: false,
  enabled: true,
  auto_enabled: false,
  auto_frequency: 100,
};

const savedCollection: EmbyCollection = {
  ...newCollectionInput,
  id: "collection-1",
};

describe("saveCollectionWithImages", () => {
  it("retries only the failed image on the saved collection", async () => {
    const poster = new File(["poster"], "poster.png", { type: "image/png" });
    const backdrop = new File(["backdrop"], "backdrop.webp", {
      type: "image/webp",
    });
    const completedUploads = {};
    let retryInput = newCollectionInput;
    const save = vi.fn(async (input: CollectionEditorInput) => {
      expect(input.id).toBe(retryInput.id);
      return { collection: savedCollection };
    });
    const upload = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("Upload backdrop non riuscito"))
      .mockResolvedValueOnce(undefined);
    const onCollectionSaved = vi.fn((collection: EmbyCollection) => {
      retryInput = { ...newCollectionInput, id: collection.id };
    });
    const options = {
      files: { poster, backdrop },
      completedUploads,
      save,
      upload,
      onCollectionSaved,
    };

    await expect(
      saveCollectionWithImages({ ...options, input: retryInput }),
    ).rejects.toThrow("Upload backdrop non riuscito");
    await expect(
      saveCollectionWithImages({ ...options, input: retryInput }),
    ).resolves.toBeUndefined();

    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[0]?.[0].id).toBeUndefined();
    expect(save.mock.calls[1]?.[0].id).toBe("collection-1");
    expect(upload).toHaveBeenCalledTimes(3);
    expect(upload.mock.calls.map(([request]) => request.kind)).toEqual([
      "poster",
      "backdrop",
      "backdrop",
    ]);
  });
});
