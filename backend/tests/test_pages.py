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


def test_home_page_is_the_front_door(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    html = res.text
    assert "<title>Trade Circle — the community and work network for contractors</title>" in html
    assert "community and work network for contractor small businesses" in html
    assert '<meta name="description"' in html and 'property="og:title"' in html
    # The real ways in: member login/signup live in the dashboard app.
    assert 'href="/app/login"' in html
    assert 'href="/app/signup"' in html
    assert "Create your free page" in html
    # Homeowners get their own strip, into the real marketplace form.
    assert "For homeowners" in html
    assert 'href="/request"' in html
    # Pricing straight from tiers.py, with the text policy per plan.
    assert "$3/mo" in html and "$9/mo" in html
    assert "one a day — your morning rundown" in html
    assert "up to two a day" in html
    assert "one weekly update email" in html
    assert "Weekly update email" in html  # the free plan's card, from FREE_FEATURES + the weekly line
    # Only what is built: nothing from the not-built list may be promised.
    assert "Google Business Profile sync" not in html
    assert "Crew sharing" not in html
    assert "Invoicing through Empire" not in html
    # No /privacy or /terms pages exist yet, so the page must not link to them.
    assert 'href="/privacy"' not in html
    assert 'href="/terms"' not in html
    assert "© Mind At Ease Solutions" in html
    csp = res.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_home_page_with_everything_configured(db, tmp_path):
    from datetime import date

    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        jwt_secret="t" * 40,
        media_dir=str(tmp_path / "media"),
        public_url="https://tradecircle.example.com",
        academy_url="https://academy.example.com",
        twilio_account_sid="AC" + "x" * 32,
        twilio_auth_token="x" * 32,
        twilio_messaging_sid="MG" + "x" * 32,
        resend_api_key="re_" + "x" * 24,
        resend_from_email="alerts@example.com",
        stripe_secret_key="sk_test_" + "x" * 24,
        stripe_webhook_secret="whsec_" + "x" * 24,
        stripe_price_starter="price_starter",
        stripe_price_full="price_full",
        ai_api_key="x" * 24,
        ai_model="test-model",
        ai_input_price=1.0,
        ai_output_price=2.0,
        ai_monthly_budget=10.0,
        encryption_key="k" * 44,
        youtube_client_id="yt-client",
        youtube_client_secret="yt-secret",
        youtube_redirect_uri="https://tradecircle.example.com/api/youtube/callback",
    )
    app = create_app(settings, db=db, today=lambda: date(2026, 10, 23))
    with TestClient(app, base_url="https://testserver") as c:
        res = c.get("/")
        assert res.status_code == 200
        assert "Create your free page" in res.text
        # The shared footer picks up the Academy link once one is configured.
        assert 'href="https://academy.example.com"' in res.text
        assert 'content="https://tradecircle.example.com/"' in res.text  # og:url


def test_unknown_paths_still_404(client, signup):
    assert client.get("/no-such-page").status_code == 404
    _, slug = _setup(client, signup)
    assert client.get(f"/p/{slug}").status_code == 200
    assert client.get("/p/no-such-pro").status_code == 404
    assert client.get("/health").json() == {"ok": True}


def test_text_color_contrast():
    assert text_color_on("#FFFFFF") == "#111111"
    assert text_color_on("#000000") == "#FFFFFF"
    assert text_color_on("#1F4E79") == "#FFFFFF"
