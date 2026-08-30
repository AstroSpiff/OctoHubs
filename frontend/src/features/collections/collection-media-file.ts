const collectionImageMimeTypes = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

const collectionImageMaxBytes = 5 * 1024 * 1024;

type CollectionMediaFile = Pick<File, "size" | "type">;

function collectionMediaFileError(
  file: CollectionMediaFile,
  label: string,
): string | null {
  if (file.size > collectionImageMaxBytes) {
    return `${label} troppo grande. Limite 5 MB.`;
  }

  if (file.type && !collectionImageMimeTypes.has(file.type)) {
    return `Formato ${label.toLocaleLowerCase("it")} non supportato.`;
  }

  return null;
}

export {
  collectionImageMaxBytes,
  collectionMediaFileError,
  type CollectionMediaFile,
};
