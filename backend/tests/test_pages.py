import json
import re

from app.profiles import text_color_on

QUOTE = {"name": "Dana Homeowner", "phone": "(512) 555-0199", "message": "Need a panel upgrade"}


def _setup(client, signup, **profile):
    headers, _ = signup("Bright Spark Electric")
    if profile:
        res = client.put("/api/me/profile", headers=headers, json=profile)
        assert res.status_code == 200, res.text
    return headers, client.get("/api/me/profile", headers=headers).json()["slug"]


def test_landing_page_renders_key_parts(client, signup):
    headers, slug = _setup(client, signup, tagline="Licensed. On time.", phone="+15125550100", facetime="+15125550100", brand_color="#FFD400")
    for n in range(8):
        client.post("/api/me/portfolio", headers=headers, json={"image_url": f"https://img.example.com/{n}.jpg", "caption": f"Job {n}"})
    res = client.get(f"/p/{slug}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    html = res.text
    assert "<title>Bright Spark Electric · Electrician in Austin</title>" in html
    assert 'href="tel:+15125550100"' in html
    # FaceTime is in the page but hidden until the script sees an Apple device.
    assert re.search(r'href="facetime:\+15125550100" data-apple-only hidden', html)
    assert html.count("<img ") == 6
    assert 'class="quote-form" data-slug="bright-spark-electric"' in html
    assert "Unverified" in html
    # Dark text on a light yellow brand color.
    assert "--brand: #FFD400; --brand-text: #111111;" in html
    assert f'href="/p/{slug}/full"' in html


def test_page_security_headers(client, signup):
    _, slug = _setup(client, signup)
    res = client.get(f"/p/{slug}")
    csp = res.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "max-age" in res.headers["strict-transport-security"]


def test_structured_data_for_search(client, signup):
    _, slug = _setup(client, signup, phone="+15125550100")
    html = client.get(f"/p/{slug}").text
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    data = json.loads(raw)
    assert data["@type"] == "LocalBusiness"
    assert data["name"] == "Bright Spark Electric"
    assert data["telephone"] == "+15125550100"


def test_user_text_is_escaped(client, signup):
    _, slug = _setup(client, signup, tagline="<script>alert(1)</script>", about="</script><b>x</b>")
    for path in (f"/p/{slug}", f"/p/{slug}/full"):
        html = client.get(path).text
        assert "<script>alert(1)" not in html
        assert "<b>x</b>" not in html
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', client.get(f"/p/{slug}").text, re.S).group(1)
    assert "</script" not in raw.lower()


def test_full_page_follows_contractor_layout(client, signup):
    _, slug = _setup(
        client,
        signup,
        about="Family owned since 2009.",
        service_area="Travis and Williamson counties",
        layout=["service_area", "about"],
        licenses=[{"name": "Master Electrician", "expires_on": "2026-01-31"}],
    )
    html = client.get(f"/p/{slug}/full").text
    order = [html.index(h) for h in ("<h2>Service area</h2>", "<h2>About</h2>", "<h2>Work</h2>", "<h2>Licenses and certifications</h2>", "<h2>Insurance</h2>", "<h2>Request a quote</h2>")]
    assert order == sorted(order)
    assert "Lapsed 2026-01-31" in html


def test_unknown_and_unpublished_pages_404(client, signup):
    headers, slug = _setup(client, signup)
    assert client.get("/p/no-such-pro").status_code == 404
    client.put("/api/me/profile", headers=headers, json={"published": False})
    res = client.get(f"/p/{slug}")
    assert res.status_code == 404
    assert "couldn't find that page" in res.text


def test_static_assets_served(client):
    assert client.get("/static/site.css").status_code == 200
    assert "quote-form" in client.get("/static/profile.js").text


def test_quote_accepts_us_phone_formats(client, signup):
    headers, slug = _setup(client, signup)
    assert client.post(f"/api/p/{slug}/quote", json=QUOTE).status_code == 202
    assert client.get("/api/inbox", headers=headers).json()[0]["phone"] == "+15125550199"


def test_text_color_contrast():
    assert text_color_on("#FFFFFF") == "#111111"
    assert text_color_on("#000000") == "#FFFFFF"
    assert text_color_on("#1F4E79") == "#FFFFFF"
