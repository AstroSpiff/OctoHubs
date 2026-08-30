import { ImageMinus, Images, Upload } from "@/components/ui/icons";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type { CollectionEditorState } from "@/features/collections/collection-editor-state";
import { collectionMediaFileError } from "@/features/collections/collection-media-file";
import type { EmbyCollection } from "@/features/collections/types";

type CollectionEditorMediaFieldsProps = {
  collection: EmbyCollection | null;
  form: CollectionEditorState;
  disabled: boolean;
  removing: "poster" | "backdrop" | null;
  removed: Record<"poster" | "backdrop", boolean>;
  onUpdate: (changes: Partial<CollectionEditorState>) => void;
  onRemove: (kind: "poster" | "backdrop") => void;
};

function CollectionEditorMediaFields({
  collection,
  form,
  disabled,
  removing,
  removed,
  onUpdate,
  onRemove,
}: CollectionEditorMediaFieldsProps) {
  return (
    <div className="collection-editor-media">
      <MediaField
        label="Poster"
        file={form.poster}
        url={form.poster_url}
        existingUrl={removed.poster ? "" : collection?.poster_blob_url}
        disabled={disabled || removing !== null}
        onFile={(poster) => onUpdate({ poster })}
        onUrl={(poster_url) => onUpdate({ poster_url })}
        onRemove={
          collection?.poster_uploaded && !removed.poster
            ? () => onRemove("poster")
            : undefined
        }
        removing={removing === "poster"}
      />
      <MediaField
        label="Sfondo"
        file={form.backdrop}
        url={form.background_url}
        existingUrl={removed.backdrop ? "" : collection?.background_blob_url}
        disabled={disabled || removing !== null}
        onFile={(backdrop) => onUpdate({ backdrop })}
        onUrl={(background_url) => onUpdate({ background_url })}
        onRemove={
          collection?.background_uploaded && !removed.backdrop
            ? () => onRemove("backdrop")
            : undefined
        }
        removing={removing === "backdrop"}
      />
    </div>
  );
}

type MediaFieldProps = {
  label: string;
  file?: File;
  url?: string;
  existingUrl?: string;
  disabled: boolean;
  onFile: (file?: File) => void;
  onUrl: (url: string) => void;
  onRemove?: () => void;
  removing: boolean;
};

function MediaField({
  label,
  file,
  url,
  existingUrl,
  disabled,
  onFile,
  onUrl,
  onRemove,
  removing,
}: MediaFieldProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState("");
  const localPreview = useMemo(
    () => (file ? URL.createObjectURL(file) : ""),
    [file],
  );

  useEffect(
    () => () => {
      if (localPreview) URL.revokeObjectURL(localPreview);
    },
    [localPreview],
  );

  const preview = localPreview || url || existingUrl;
  const canRemove = Boolean(file || url || existingUrl);

  function selectFile(nextFile?: File) {
    if (!nextFile) {
      setFileError("");
      onFile(undefined);
      return;
    }

    const error = collectionMediaFileError(nextFile, label);
    if (error) {
      setFileError(error);
      return;
    }

    setFileError("");
    onFile(nextFile);
  }

  function removeMedia() {
    setFileError("");
    if (file) {
      onFile(undefined);
      return;
    }
    if (existingUrl && onRemove) {
      onRemove();
      return;
    }
    onUrl("");
  }

  return (
    <section className="collection-editor-media-field">
      <header>
        <strong>{label}</strong>
        {canRemove ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title={`Rimuovi ${label.toLocaleLowerCase("it")}`}
            aria-label={`Rimuovi ${label.toLocaleLowerCase("it")}`}
            onClick={removeMedia}
            disabled={disabled}
          >
            <ImageMinus size={15} aria-hidden="true" />
          </Button>
        ) : null}
      </header>
      {preview ? (
        <img src={preview} alt="" />
      ) : (
        <div>
          <Images size={22} aria-hidden="true" />
        </div>
      )}
      <label>
        <span>URL immagine</span>
        <input
          value={url}
          disabled={disabled}
          onChange={(event) => {
            setFileError("");
            onUrl(event.target.value);
          }}
          placeholder="https://..."
        />
      </label>
      <label
        htmlFor={inputId}
        className={`collection-editor-dropzone${dragging ? " is-dragging" : ""}${disabled ? " is-disabled" : ""}`}
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          inputRef.current?.click();
        }}
        onDragEnter={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!disabled) selectFile(event.dataTransfer.files[0]);
        }}
      >
        <Upload size={16} aria-hidden="true" />
        <strong>{removing ? "Rimozione..." : `Carica ${label}`}</strong>
        <small>JPEG, PNG o WebP. Massimo 5 MB.</small>
      </label>
      <input
        ref={inputRef}
        id={inputId}
        className="collection-editor-file-input"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        disabled={disabled}
        onChange={(event) => {
          selectFile(event.target.files?.[0]);
          event.currentTarget.value = "";
        }}
      />
      {fileError ? (
        <p className="collection-editor-media-error" role="alert">
          {fileError}
        </p>
      ) : null}
    </section>
  );
}

export { CollectionEditorMediaFields };
