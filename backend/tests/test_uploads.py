import io
from pathlib import Path

from PIL import Image

from app import media
from app.routers import portfolio as portfolio_router

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def jpeg_with_gps(size=(400, 300), orientation=6):
    """A phone-style JPEG: GPS position of the job site and a 'rotate 90°' flag."""
    img = Image.new("RGB", size, (200, 80, 40))
    exif = Image.Exif()
    exif[ORIENTATION] = orientation
    exif[0x010F] = "PhoneMaker"
    gps = exif.get_ifd(GPS_IFD)
    gps[1], gps[2], gps[3], gps[4] = "N", (30.0, 16.0, 4.0), "W", (97.0, 44.0, 35.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    data = buf.getvalue()
    assert Image.open(io.BytesIO(data)).getexif().get_ifd(GPS_IFD)  # the test photo really has GPS
    return data


def png_with_alpha():
    img = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def upload(client, headers, data, name="job.jpg", caption="Panel swap", content_type="image/jpeg"):
    return client.post(
        "/api/me/portfolio/upload",
        headers=headers,
        files={"file": (name, data, content_type)},
        data={"caption": caption},
    )


def stored(settings, url):
    return Path(settings.media_dir) / url.removeprefix("/media/")


def test_upload_strips_location_and_fixes_rotation(client, signup, settings):
    headers, _ = signup()
    res = upload(client, headers, jpeg_with_gps())
    assert res.status_code == 201, res.text
    item = res.json()
    assert item["caption"] == "Panel swap"
    # Stored the right way up: the phone's sideways 400x300 becomes 300x400.
    assert (item["width"], item["height"]) == (300, 400)

    for url in (item["image_url"], item["thumb_url"]):
        with Image.open(stored(settings, url)) as saved:
            assert saved.format == "JPEG"
            assert not saved.getexif(), "no metadata at all, so no GPS"
            assert "exif" not in saved.info
    with Image.open(stored(settings, item["thumb_url"])) as thumb:
        assert thumb.size == (media.THUMB_SIZE, media.THUMB_SIZE)

    served = client.get(item["image_url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"


def test_large_photos_are_shrunk(client, signup):
    headers, _ = signup()
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), (10, 120, 200)).save(buf, "JPEG")
    item = upload(client, headers, buf.getvalue()).json()
    assert (item["width"], item["height"]) == (1600, 1200)


def test_png_with_transparency_is_accepted(client, signup):
    headers, _ = signup()
    res = upload(client, headers, png_with_alpha(), name="logo.png", content_type="image/png")
    assert res.status_code == 201


def test_non_photos_are_refused(client, signup):
    headers, _ = signup()
    assert upload(client, headers, b"not an image at all", name="notes.txt", content_type="text/plain").status_code == 422
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    res = upload(client, headers, gif.getvalue(), name="a.gif", content_type="image/gif")
    assert res.status_code == 422 and "JPEG, PNG or WebP" in res.json()["detail"]
    # Lying about the type doesn't help: the content is checked, not the name.
    assert upload(client, headers, b"<script>alert(1)</script>", name="x.jpg").status_code == 422
    assert client.get("/api/me/portfolio", headers=headers).json() == []


def test_oversized_files_and_huge_images_are_refused(client, signup, monkeypatch):
    headers, _ = signup()
    monkeypatch.setattr(media, "MAX_UPLOAD_BYTES", 1000)
    res = upload(client, headers, jpeg_with_gps())
    assert res.status_code == 413 and "15 MB" in res.json()["detail"]
    monkeypatch.setattr(media, "MAX_UPLOAD_BYTES", 15 * 1024 * 1024)
    monkeypatch.setattr(media, "MAX_PIXELS", 1000)
    res = upload(client, headers, jpeg_with_gps())
    assert res.status_code == 422 and "too large" in res.json()["detail"]


def test_public_pages_use_thumbnails_and_full_preview_links(client, signup):
    headers, _ = signup()
    item = upload(client, headers, jpeg_with_gps()).json()
    slug = client.get("/api/me/profile", headers=headers).json()["slug"]
    html = client.get(f"/p/{slug}").text
    assert f'src="{item["thumb_url"]}"' in html
    assert f'href="{item["image_url"]}"' in html
    assert f'content="https://tradecircle.mindateasesolutions.com{item["image_url"]}"' in html


def test_caption_edit_delete_and_isolation(client, signup, settings):
    owner, _ = signup()
    other, _ = signup("Other Co", trade="painter")
    item = upload(client, owner, jpeg_with_gps()).json()
    assert client.patch(f"/api/me/portfolio/{item['id']}", headers=other, json={"caption": "x"}).status_code == 404
    assert client.patch(f"/api/me/portfolio/{item['id']}", headers=owner, json={"caption": "200A panel"}).json()["caption"] == "200A panel"
    assert client.delete(f"/api/me/portfolio/{item['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/me/portfolio/{item['id']}", headers=owner).status_code == 204
    assert not stored(settings, item["image_url"]).exists()
    assert not stored(settings, item["thumb_url"]).exists()


def test_photo_count_is_capped(client, signup, monkeypatch):
    headers, _ = signup()
    monkeypatch.setattr(portfolio_router, "MAX_PHOTOS", 2)
    assert [upload(client, headers, jpeg_with_gps()).status_code for _ in range(3)] == [201, 201, 409]
    linked = client.post("/api/me/portfolio", headers=headers, json={"image_url": "https://img.example.com/x.jpg"})
    assert linked.status_code == 409


def test_media_store_refuses_paths_outside_its_folder(tmp_path):
    store = media.LocalMediaStore(tmp_path)
    try:
        store.save("../escape.jpg", b"x")
        raise AssertionError("expected refusal")
    except ValueError:
        pass
    assert not (tmp_path.parent / "escape.jpg").exists()
