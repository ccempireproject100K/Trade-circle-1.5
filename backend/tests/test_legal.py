"""The public legal pages: /privacy and /terms.

Server-rendered from the texts in app/legal/, readable logged out (members,
reviewers and ad networks read them without an account). The drafts'
bracketed blanks resolve from the app settings — entity always, contact
email/address only when configured — and no placeholder may ever render.
"""
import re
from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.main import create_app

BRACKETS = re.compile(r"\[[^\]\n]{2,}\](?!\()")


def _no_placeholders(html):
    for token in (
        "[EFFECTIVE DATE]",
        "[OWNER NAME / BUSINESS ENTITY]",
        "[SUPPORT EMAIL]",
        "[MAILING ADDRESS]",
        "[GOVERNING STATE",
        "OWNER/ATTORNEY",
        "DRAFT",
    ):
        assert token not in html
    assert BRACKETS.findall(html) == []


def test_privacy_page_renders_logged_out(client):
    res = client.get("/privacy")  # no auth headers: the fixture client is anonymous
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    html = res.text
    assert "<title>Privacy Policy · Trade Circle</title>" in html
    assert "<h1>Privacy Policy</h1>" in html
    assert "Last updated: October 23, 2026" in html
    # The default entity, and the section structure of the policy.
    assert "operated by <strong>Mind At Ease Solutions</strong>" in html
    for heading in ("1. Accounts", "3. Leads and customer information", "5. The YouTube integration (optional)", "12. Contact"):
        assert f"<h2>{heading}</h2>" in html
    assert "we do not sell personal information" in html
    # The Google/YouTube policy links survive as real links.
    assert '<a href="https://www.youtube.com/t/terms">YouTube Terms of Service</a>' in html
    assert '<a href="https://policies.google.com/privacy">Google Privacy Policy</a>' in html
    assert '<a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>' in html
    # Front-door chrome: wood header, and the shared footer links both pages.
    assert 'class="site-header wood-grain"' in html
    assert 'href="/privacy"' in html and 'href="/terms"' in html
    csp = res.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    _no_placeholders(html)


def test_terms_page_renders_logged_out(client):
    res = client.get("/terms")
    assert res.status_code == 200
    html = res.text
    assert "<title>Terms of Service · Trade Circle</title>" in html
    assert "<h1>Terms of Service</h1>" in html
    assert "Last updated: October 23, 2026" in html
    assert "agreement between you and <strong>Mind At Ease Solutions</strong>" in html
    for heading in ("1. Accounts", "4. Your content — you keep your rights", "8. Liability", "10. Governing law and disputes"):
        assert f"<h2>{heading}</h2>" in html
    assert "<h3>The YouTube integration specifically</h3>" in html
    # The liability cap keeps the draft's conservative wording, flag removed.
    assert "limited to the amount you paid Trade Circle in the twelve months before the claim" in html
    assert "(or $100 if you are on the free plan, whichever framework the law allows)" in html
    # Governing law and venue defaults.
    assert "governed by the laws of <strong>Texas</strong>" in html
    assert "courts located in <strong>Tarrant County, Texas</strong>" in html
    # No arbitration/carve-out drafting note leaks into the published text.
    assert "arbitration" not in html
    _no_placeholders(html)


def test_contact_block_omits_unset_lines(client):
    # Default settings: no TC_LEGAL_EMAIL / TC_LEGAL_ADDRESS, so the contact
    # block names the entity only — no empty Email:/Mailing address: lines.
    for path in ("/privacy", "/terms"):
        html = client.get(path).text
        assert "<strong>Mind At Ease Solutions</strong>" in html
        assert "Email:" not in html
        assert "Mailing address:" not in html
    # The one mid-sentence use drops its phrase cleanly when no email is set.
    terms = client.get("/terms").text
    assert "Tell us promptly if you suspect unauthorized use." in terms


def test_legal_pages_follow_settings(db, tmp_path, monkeypatch):
    settings = Settings(
        jwt_secret="t" * 40,
        media_dir=str(tmp_path / "media"),
        legal_entity="Acme Holdings LLC",
        legal_email="help@acme.example",
        legal_address="PO Box 1, Fort Worth, TX 76101",
    )
    app = create_app(settings, db=db, today=lambda: date(2026, 10, 23))
    with TestClient(app, base_url="https://testserver") as c:
        for path in ("/privacy", "/terms"):
            html = c.get(path).text
            assert "Acme Holdings LLC" in html
            assert "Email: <strong>help@acme.example</strong>" in html
            assert "Mailing address: <strong>PO Box 1, Fort Worth, TX 76101</strong>" in html
            _no_placeholders(html)
        assert "Tell us promptly at <strong>help@acme.example</strong> if you suspect" in c.get("/terms").text
    # The same values arrive from the environment.
    monkeypatch.setenv("TC_JWT_SECRET", "t" * 40)
    monkeypatch.setenv("TC_LEGAL_ENTITY", "Env Entity LLC")
    monkeypatch.setenv("TC_LEGAL_EMAIL", "env@example.com")
    monkeypatch.setenv("TC_LEGAL_ADDRESS", "1 Main St, Fort Worth, TX")
    loaded = load_settings()
    assert loaded.legal_entity == "Env Entity LLC"
    assert loaded.legal_email == "env@example.com"
    assert loaded.legal_address == "1 Main St, Fort Worth, TX"


def test_legal_defaults_when_env_unset(monkeypatch):
    monkeypatch.setenv("TC_JWT_SECRET", "t" * 40)
    for var in ("TC_LEGAL_ENTITY", "TC_LEGAL_EMAIL", "TC_LEGAL_ADDRESS"):
        monkeypatch.delenv(var, raising=False)
    loaded = load_settings()
    assert loaded.legal_entity == "Mind At Ease Solutions"
    assert loaded.legal_email == "" and loaded.legal_address == ""
