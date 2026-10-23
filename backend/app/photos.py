"""Receive, clean and store an uploaded photo. Shared by the portfolio and community posts."""
import asyncio
import uuid

from fastapi import HTTPException, Request, UploadFile, status

from . import media

TOO_LARGE = "That photo is over 15 MB. Please choose a smaller one."


async def _read_limited(upload: UploadFile) -> bytes:
    chunks, size = [], 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > media.MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


async def ingest(request: Request, upload: UploadFile, owner_id: str, folder: str) -> dict:
    """Clean the photo (metadata removed, upright, resized) and save full and thumbnail copies."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > media.MAX_UPLOAD_BYTES + 64 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE)
    data = await _read_limited(upload)
    try:
        # Decoding and resizing is CPU work; keep it off the event loop.
        cleaned = await asyncio.to_thread(media.process, data)
    except media.BadImage as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    photo_id = uuid.uuid4().hex
    store = request.app.state.media
    full_key = f"{folder}/{owner_id}/{photo_id}.jpg"
    thumb_key = f"{folder}/{owner_id}/{photo_id}-thumb.jpg"
    store.save(full_key, cleaned["full"])
    store.save(thumb_key, cleaned["thumb"])
    return {
        "id": photo_id,
        "image_url": store.url(full_key),
        "thumb_url": store.url(thumb_key),
        "media_keys": [full_key, thumb_key],
        "width": cleaned["width"],
        "height": cleaned["height"],
    }


def discard(request: Request, photo: dict) -> None:
    for key in photo.get("media_keys", []):
        request.app.state.media.delete(key)
