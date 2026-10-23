"""Short project video clips for walkthroughs.

Every clip is re-encoded with ffmpeg on our own server: that removes all
metadata (phones record GPS in video files too), caps the length and size, and
gives every browser a file it can play. Members can trim the start and end and
remove the sound before publishing; each edit makes a new file from the
cleaned copy. Blurring faces or house numbers isn't offered: it needs a
detection service or manual editing tools, which are a separate cost decision.
Until then, members trim those parts out or replace the clip.

If ffmpeg isn't installed, video uploads are switched off and photos still work.
"""
import asyncio
import json
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile, status

from . import media

MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_SECONDS = 180
WIDTH = 1280
TIMEOUT = 600
# Re-encoding is CPU-heavy; only a couple at a time per server.
_slots = asyncio.Semaphore(2)


def available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


async def _run(*args: str, timeout: int = TIMEOUT) -> bytes:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That video took too long to process. Try a shorter clip.")
    if proc.returncode != 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "We couldn't read that video. Try an MP4 or MOV from your phone.")
    return out


async def probe(path: Path) -> dict:
    out = await _run("ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path), timeout=60)
    info = json.loads(out or b"{}")
    streams = info.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That file doesn't contain a video.")
    return {"duration": float(info.get("format", {}).get("duration") or 0), "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


async def encode(src: Path, dest: Path, start: float = 0.0, end: float | None = None, mute: bool = False) -> None:
    """Re-encode from pixels and sound only: no metadata, chapters or extra streams survive."""
    args = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src)]
    length = (end - start) if end is not None else MAX_SECONDS
    args += ["-t", f"{min(length, MAX_SECONDS):.2f}", "-map", "0:v:0"]
    if not mute:
        args += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "96k", "-ac", "2"]
    args += [
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-vf", f"scale='min({WIDTH},iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(dest),
    ]
    async with _slots:
        await _run(*args)


async def poster(src: Path) -> bytes:
    out = await _run("ffmpeg", "-nostdin", "-v", "error", "-ss", "0.5", "-i", str(src), "-frames:v", "1", "-f", "image2", "-c:v", "png", "-", timeout=60)
    return (await asyncio.to_thread(media.process, out))["thumb"]


async def _store(request: Request, owner_id: str, cleaned: Path, info: dict) -> dict:
    video_id = uuid.uuid4().hex
    store = request.app.state.media
    video_key = f"videos/{owner_id}/{video_id}.mp4"
    thumb_key = f"videos/{owner_id}/{video_id}-poster.jpg"
    store.save(video_key, cleaned.read_bytes())
    store.save(thumb_key, await poster(cleaned))
    return {"id": video_id, "type": "video", "video_url": store.url(video_key), "thumb_url": store.url(thumb_key), "image_url": store.url(thumb_key), "duration": round(info["duration"], 1), "has_audio": info["has_audio"], "media_keys": [video_key, thumb_key]}


async def ingest(request: Request, upload: UploadFile, owner_id: str) -> dict:
    if not available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Video clips aren't available on this server yet. Photos still work.")
    with tempfile.TemporaryDirectory() as tmp:
        raw, cleaned = Path(tmp) / "upload", Path(tmp) / "clean.mp4"
        size = 0
        with raw.open("wb") as f:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "That video is over 200 MB. Trim it on your phone first or pick a shorter clip.")
                f.write(chunk)
        info = await probe(raw)
        if info["duration"] > MAX_SECONDS + 1:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Clips can be up to {MAX_SECONDS // 60} minutes. Trim it on your phone first.")
        await encode(raw, cleaned)
        return await _store(request, owner_id, cleaned, await probe(cleaned))


async def edit(request: Request, source: dict, owner_id: str, start: float, end: float | None, mute: bool) -> dict:
    """Make a new clip from an already-cleaned one."""
    src = Path(request.app.state.media.root) / source["media_keys"][0]
    with tempfile.TemporaryDirectory() as tmp:
        cleaned = Path(tmp) / "edit.mp4"
        await encode(src, cleaned, start, end, mute)
        return await _store(request, owner_id, cleaned, await probe(cleaned))
