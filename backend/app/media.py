"""Photo uploads: clean up the image, then store it.

Phone photos carry GPS coordinates in their metadata, which for a job photo is
the customer's home. Every upload is re-encoded from its pixels only, so no
metadata survives. Photos are also turned the right way up (phones often store
them sideways with a rotation flag), shrunk for fast pages, and given a square
thumbnail for the photo grid.

Files are stored on local disk and served at /media. To move to object storage
(for example Cloudflare R2), add a store with the same save/delete/url methods.
"""
import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 60_000_000  # about 60 megapixels; anything bigger is refused
FULL_SIZE = 1600
THUMB_SIZE = 600
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class BadImage(ValueError):
    pass


def _to_jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    # Saved without exif or other metadata.
    img.save(out, "JPEG", quality=82, optimize=True, progressive=True)
    return out.getvalue()


def process(data: bytes) -> dict:
    """Validate and clean an uploaded photo. Returns full and thumbnail JPEG bytes."""
    with warnings.catch_warnings():
        # Treat oversized images ("decompression bombs") as errors, not warnings.
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        previous = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        try:
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ACCEPTED_FORMATS:
                    raise BadImage("Photos must be JPEG, PNG or WebP.")
                img = ImageOps.exif_transpose(source)
                if img.mode in ("RGBA", "LA", "P"):
                    rgba = img.convert("RGBA")
                    background = Image.new("RGB", rgba.size, (255, 255, 255))
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    img = background
                else:
                    img = img.convert("RGB")
                # Rebuild from raw pixels so nothing from the original file carries over.
                clean = Image.frombytes("RGB", img.size, img.tobytes())
        except (Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise BadImage("That photo is too large. Please use one under 60 megapixels.")
        except (UnidentifiedImageError, OSError, SyntaxError):
            raise BadImage("That file isn't a photo we can read. Please use a JPEG, PNG or WebP image.")
        finally:
            Image.MAX_IMAGE_PIXELS = previous

    full = clean.copy()
    full.thumbnail((FULL_SIZE, FULL_SIZE), Image.Resampling.LANCZOS)
    thumb = ImageOps.fit(clean, (THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
    return {"full": _to_jpeg(full), "thumb": _to_jpeg(thumb), "width": full.width, "height": full.height}


class LocalMediaStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("bad media key")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    @staticmethod
    def url(key: str) -> str:
        return f"/media/{key}"
