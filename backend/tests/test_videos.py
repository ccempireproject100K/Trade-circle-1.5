"""Walkthrough video clips: metadata removed, trim and mute, attached to posts like photos."""
import json
import shutil
import subprocess

import pytest

from app import videos

pytestmark = pytest.mark.skipif(not videos.available(), reason="ffmpeg not installed")


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.mov"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=15", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "6",
         "-metadata", "location=+30.2672-097.7431/", "-metadata", "title=Customer house", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path.read_bytes()


def _tags(path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], capture_output=True, check=True).stdout
    return json.loads(out)


def test_clip_lifecycle(client, signup, settings, clip):
    h, user = signup()
    res = client.post("/api/media/videos", files={"file": ("clip.mov", clip, "video/quicktime")}, headers=h)
    assert res.status_code == 201, res.text
    up = res.json()
    assert up["type"] == "video" and up["has_audio"] and 5 <= up["duration"] <= 7 and "media_keys" not in up
    stored = settings.media_dir + up["video_url"].removeprefix("/media")
    info = _tags(stored)
    tags = info["format"].get("tags", {})
    assert "location" not in tags and "title" not in tags
    assert all("location" not in s.get("tags", {}) for s in info["streams"])

    # Trim and remove the sound: a new clip replaces the old one.
    edited = client.post(f"/api/media/videos/{up['id']}/edit", json={"start": 1, "end": 3, "mute": True}, headers=h)
    assert edited.status_code == 201, edited.text
    new = edited.json()
    assert new["has_audio"] is False and 1.5 <= new["duration"] <= 2.6
    assert client.post(f"/api/media/videos/{up['id']}/edit", json={"start": 0, "end": 2}, headers=h).status_code == 404  # old one is gone

    post = client.post("/api/posts", json={"kind": "lesson", "title": "Clip", "photos": [{"id": new["id"], "group": ""}], "publish": True}, headers=h)
    assert post.status_code == 201, post.text
    attached = post.json()["photos"][0]
    assert attached["type"] == "video" and attached["video_url"] == new["video_url"] and attached["thumb_url"].endswith(".jpg")

    # Someone else can't use or edit it.
    other, _ = signup()
    assert client.post(f"/api/media/videos/{new['id']}/edit", json={"mute": True}, headers=other).status_code == 404
    assert client.post("/api/posts", json={"kind": "lesson", "title": "x", "photos": [{"id": new["id"]}], "publish": True}, headers=other).status_code == 422


def test_rejects_non_video_and_overlong(client, signup, clip, monkeypatch):
    h, _ = signup()
    assert client.post("/api/media/videos", files={"file": ("x.mp4", b"not a video", "video/mp4")}, headers=h).status_code == 422
    monkeypatch.setattr(videos, "MAX_SECONDS", 3)
    res = client.post("/api/media/videos", files={"file": ("clip.mov", clip, "video/quicktime")}, headers=h)
    assert res.status_code == 422 and "up to" in res.json()["detail"]


def test_off_without_ffmpeg(client, signup, monkeypatch, clip):
    h, _ = signup()
    monkeypatch.setattr(shutil, "which", lambda name: None)
    res = client.post("/api/media/videos", files={"file": ("clip.mov", clip, "video/quicktime")}, headers=h)
    assert res.status_code == 503 and "Photos still work" in res.json()["detail"]
