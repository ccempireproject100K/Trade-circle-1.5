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
    assert "<title>Trade Circle — the community and work network for contractors and small businesses alike</title>" in html
    assert "The community and work network for contractors and small businesses alike" in html
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
    assert "No texts — a weekly update by email." in html
    assert "You get one text a day." in html
    assert "You get two texts a day." in html
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


def test_home_page_has_a_new_businesses_section(client):
    # Owner addition (2026-10-23): a little section for brand-new small
    # businesses and first-time entrepreneurs, with the audience sections
    # (after "For homeowners", before pricing) and the free-page CTA.
    html = client.get("/").text
    assert "Just starting out?" in html
    assert "your first storefront" in html
    assert "price your first jobs right" in html
    assert html.index("For homeowners") < html.index("Just starting out?") < html.index("Simple pricing")
    section = html[html.index("Just starting out?"):html.index("Simple pricing")]
    assert 'href="/app/signup"' in section and "Create your free page" in section
    # The section names the community's Starting Out lane: starter tips,
    # new-owner meetups, and mentors (a real post kind, not a promise).
    assert "Starting Out" in section and "starter tips" in section and "mentor" in section
    # Only what's built: no unbuilt promises in the section.
    assert "Google Business Profile sync" not in section
    assert "Invoicing through Empire" not in section


def test_front_door_references_the_illustrations(client):
    html = client.get("/").text
    assert 'src="/static/img/hero.webp"' in html
    assert 'src="/static/img/handoff.webp"' in html
    assert 'src="/static/img/reviews.webp"' in html


def test_platform_illustrations_are_served_as_webp(client):
    for name in ("hero", "handoff", "reviews"):
        res = client.get(f"/static/img/{name}.webp")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/webp"
        assert "max-age=31536000" in res.headers["cache-control"]
        # A real WebP file: RIFF container with the WEBP form type.
        assert res.content[:4] == b"RIFF" and res.content[8:12] == b"WEBP"
    assert client.get("/static/img/nope.webp").status_code == 404


def test_illustration_routes_serve_the_encoded_artwork(client):
    # What the route serves is byte-for-byte the base64 artwork on disk —
    # the green-free redraws swapped in for the final Slice 16 palette.
    import base64
    from pathlib import Path

    img_dir = Path(__file__).resolve().parent.parent / "app" / "static" / "img"
    for name in ("hero", "handoff", "reviews"):
        expected = base64.b64decode((img_dir / f"{name}.webp.b64").read_bytes())
        res = client.get(f"/static/img/{name}.webp")
        assert res.status_code == 200
        assert res.content == expected


def test_home_page_groups_features_by_plan(client):
    # Owner ruling (2026-10-23): the Free/Starter/Full labels were scattered
    # through the page as per-feature badges. Now "What you get" is three
    # headed groups in plan order, and the heading carries the tier.
    html = client.get("/").text
    free_at = html.index("On every free page")
    starter_at = html.index("Starter adds")
    full_at = html.index("Full adds")
    assert free_at < starter_at < full_at
    # No scattered tier badges on the feature cards anymore.
    assert '<span class="badge">Starter</span>' not in html
    assert '<span class="badge">Full</span>' not in html
    # Every feature sits under its own group, exactly where its plan puts it.
    assert free_at < html.index("Your public page") < starter_at
    assert free_at < html.index("Handoffs &amp; vacation coverage") < starter_at
    assert starter_at < html.index("The daily rundown") < full_at
    assert starter_at < html.index("Time tracking") < full_at
    assert starter_at < html.index("YouTube auto-posting") < full_at
    assert full_at < html.index("Customer payments")
    # Each pricing card states only its own text allowance (owner's words):
    # the Starter card must not talk about what Full gets, and vice versa.
    assert "No texts — a weekly update by email." in html
    assert "You get one text a day." in html
    assert "You get two texts a day." in html
    assert "1 text a day on Starter" not in html
    assert "up to 2 on Full" not in html


def test_home_page_uses_the_final_tagline(client):
    # Owner's exact words (2026-10-23): the front door's title reads
    # "the community and work network for contractors and small businesses alike".
    html = client.get("/").text
    assert "<title>Trade Circle — the community and work network for contractors and small businesses alike</title>" in html
    assert "<h1>The community and work network for contractors and small businesses alike</h1>" in html
    # The crew picture is the hero's faded backdrop, behind the words and
    # both calls to action — not a side-by-side image anymore.
    assert 'class="hero-backdrop"' in html
    assert 'class="hero-art"' not in html


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
