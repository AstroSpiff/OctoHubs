"""Decode and normalize untrusted raster image uploads."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO
import warnings

from PIL import Image, ImageOps


MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 10_000_000
SAFE_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

_SAFE_IMAGE_FORMATS = ("JPEG", "PNG", "WEBP")
_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class ImageUploadError(ValueError):
    """Raised when uploaded bytes cannot be stored and served as a safe image."""


@dataclass(frozen=True)
class SanitizedImage:
    data: bytes
    mime_type: str
    width: int
    height: int


def _validate_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise ImageUploadError("Risoluzione immagine troppo elevata")


def _safe_pixel_mode(image: Image.Image) -> str:
    has_alpha = "A" in image.getbands() or (
        image.mode == "P" and "transparency" in image.info
    )
    return "RGBA" if has_alpha else "RGB"


def _encode_image(image: Image.Image, image_format: str) -> bytes:
    normalized = ImageOps.exif_transpose(image).convert(_safe_pixel_mode(image))
    normalized.info.clear()
    output = BytesIO()
    if image_format == "JPEG":
        normalized = normalized.convert("RGB")
        normalized.save(output, format="JPEG", quality=90, progressive=True)
    elif image_format == "PNG":
        normalized.save(output, format="PNG", compress_level=6)
    else:
        normalized.save(output, format="WEBP", quality=90, method=4)
    encoded = output.getvalue()
    if len(encoded) > MAX_IMAGE_UPLOAD_BYTES:
        raise ImageUploadError("Immagine ricodificata troppo grande. Limite 5 MB.")
    return encoded


def sanitize_image_bytes(data: bytes) -> SanitizedImage:
    """Validate by decoded content and return metadata-free canonical raster bytes."""
    if not isinstance(data, bytes) or not data:
        raise ImageUploadError("File immagine vuoto")
    if len(data) > MAX_IMAGE_UPLOAD_BYTES:
        raise ImageUploadError("Immagine troppo grande. Limite 5 MB.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=_SAFE_IMAGE_FORMATS) as candidate:
                image_format = str(candidate.format or "").upper()
                if image_format not in _MIME_BY_FORMAT:
                    raise ImageUploadError("Formato immagine non supportato")
                _validate_dimensions(candidate)
                candidate.verify()

            with Image.open(BytesIO(data), formats=_SAFE_IMAGE_FORMATS) as decoded:
                _validate_dimensions(decoded)
                decoded.seek(0)
                decoded.load()
                width, height = decoded.size
                encoded = _encode_image(decoded, image_format)
    except ImageUploadError:
        raise
    except Exception as exc:
        raise ImageUploadError(
            "Formato immagine non supportato o contenuto non valido"
        ) from exc

    return SanitizedImage(
        data=encoded,
        mime_type=_MIME_BY_FORMAT[image_format],
        width=width,
        height=height,
    )


def sanitize_image_file(file_obj: BinaryIO) -> SanitizedImage:
    """Read at most the configured upload limit from a binary file object."""
    file_obj.seek(0)
    data = file_obj.read(MAX_IMAGE_UPLOAD_BYTES + 1)
    if not isinstance(data, bytes):
        raise ImageUploadError("Contenuto immagine non valido")
    return sanitize_image_bytes(data)


__all__ = [
    "ImageUploadError",
    "MAX_IMAGE_PIXELS",
    "MAX_IMAGE_UPLOAD_BYTES",
    "SAFE_IMAGE_MIME_TYPES",
    "SanitizedImage",
    "sanitize_image_bytes",
    "sanitize_image_file",
]
