import type {
  CollectionEditorInput,
  EmbyCollection,
} from "@/features/collections/types";

type CollectionImageKind = "poster" | "backdrop";
type CollectionImageFiles = Partial<Record<CollectionImageKind, File>>;

type CompletedCollectionImageUploads = CollectionImageFiles & {
  collectionId?: string;
};

type SaveCollectionWithImagesOptions = {
  input: CollectionEditorInput;
  files: CollectionImageFiles;
  completedUploads: CompletedCollectionImageUploads;
  save: (input: CollectionEditorInput) => Promise<{ collection: EmbyCollection }>;
  upload: (request: {
    collectionId: string;
    kind: CollectionImageKind;
    file: File;
  }) => Promise<unknown>;
  onCollectionSaved: (collection: EmbyCollection) => void;
};

const collectionImageKinds = ["poster", "backdrop"] as const;

async function saveCollectionWithImages({
  input,
  files,
  completedUploads,
  save,
  upload,
  onCollectionSaved,
}: SaveCollectionWithImagesOptions): Promise<void> {
  const result = await save(input);
  const collectionId = result.collection.id;
  onCollectionSaved(result.collection);

  if (completedUploads.collectionId !== collectionId) {
    completedUploads.collectionId = collectionId;
    delete completedUploads.poster;
    delete completedUploads.backdrop;
  }

  for (const kind of collectionImageKinds) {
    const file = files[kind];
    if (!file || completedUploads[kind] === file) continue;

    await upload({ collectionId, kind, file });
    completedUploads[kind] = file;
  }

  delete completedUploads.collectionId;
  delete completedUploads.poster;
  delete completedUploads.backdrop;
}

export {
  saveCollectionWithImages,
  type CollectionImageFiles,
  type CompletedCollectionImageUploads,
};
