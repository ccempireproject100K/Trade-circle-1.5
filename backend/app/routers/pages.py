"""Server-rendered public pages: fast on phones and readable by search engines."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from ..deps import get_db, today
from ..models import TRADES
from ..profiles import DEFAULT_BRAND_COLOR, full_view, landing_view, text_color_on
from .profiles import featured_projects, team_on_profile, portfolio_for, published_profile

router = APIRouter(tags=["pages"], include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

PAGE_CSP = (
    "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
# The dashboard also embeds the official YouTube player (Break Room music) and serves
# self-hosted games, which the dashboard itself frames.
DASHBOARD_CSP = (
    "default-src 'self'; img-src 'self' https: data:; media-src 'self'; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' https://www.youtube.com https://s.ytimg.com; frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
GAME_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
TRADE_LABELS = {t: t.replace("_", " ").title() for t in TRADES}
TRADE_LABELS["hvac"] = "HVAC"


def _absolute(url: str, public_url: str) -> str:
    """Link previews and search engines need full addresses, not /media/... paths."""
    return f"{public_url}{url}" if url.startswith("/") else url


def _structured_data(page: dict, trade_label: str, public_url: str) -> dict:
    """schema.org LocalBusiness, so search engines can show the business properly."""
    data = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": page["business_name"],
        "description": page["tagline"] or f"{trade_label} in {page['city']}",
        "areaServed": page["city"],
    }
    if "tel" in page["call"]:
        data["telephone"] = page["call"]["tel"].removeprefix("tel:")
    if page["portfolio"]:
        data["image"] = _absolute(page["portfolio"][0]["image_url"], public_url)
    return data


async def _render(request: Request, db, slug: str, layer: str) -> HTMLResponse:
    try:
        profile = await published_profile(db, slug)
    except HTTPException:
        response = templates.TemplateResponse(
            request, "not_found.html", {"academy_url": request.app.state.settings.academy_url}, status_code=404
        )
        response.headers["Content-Security-Policy"] = PAGE_CSP
        return response
    portfolio = await portfolio_for(db, profile["owner_id"])
    settings = request.app.state.settings
    if layer == "full":
        projects = await featured_projects(db, profile["owner_id"])
        page = full_view(profile, portfolio, today(request), settings.recert_banner_days, projects)
        page["team"] = await team_on_profile(db, profile["owner_id"])
    else:
        page = landing_view(profile, portfolio, today(request), settings.recert_banner_days)
    brand = page["brand_color"] or DEFAULT_BRAND_COLOR
    trade_label = TRADE_LABELS.get(page["trade"], page["trade"])
    response = templates.TemplateResponse(
        request,
        f"{layer}.html",
        {
            "p": page,
            "brand": brand,
            "brand_text": text_color_on(brand),
            "trade_label": trade_label,
            "structured_data": _structured_data(page, trade_label, settings.public_url),
            "academy_url": settings.academy_url,
        },
    )
    response.headers["Content-Security-Policy"] = PAGE_CSP
    response.headers["Cache-Control"] = "public, max-age=60"
    return response


@router.get("/p/{slug}", response_class=HTMLResponse)
async def landing_page(slug: str, request: Request, db=Depends(get_db)):
    return await _render(request, db, slug, "landing")


@router.get("/p/{slug}/full", response_class=HTMLResponse)
async def full_page(slug: str, request: Request, db=Depends(get_db)):
    return await _render(request, db, slug, "full")


@router.get("/suppliers/{supplier_id}/remove", response_class=HTMLResponse)
async def removal_page(supplier_id: str, request: Request, db=Depends(get_db)):
    """Public page where a business asks for its directory listing to be removed."""
    supplier = await db.suppliers.find_one({"_id": supplier_id, "status": "active"}, {"name": 1})
    settings = request.app.state.settings
    if supplier is None:
        response = templates.TemplateResponse(request, "not_found.html", {"academy_url": settings.academy_url}, status_code=404)
    else:
        response = templates.TemplateResponse(request, "removal.html", {"name": supplier["name"], "supplier_id": supplier_id, "academy_url": settings.academy_url})
    response.headers["Content-Security-Policy"] = PAGE_CSP
    return response


# The contractor dashboard: a single-page app built from frontend/ into frontend/dist.
DASHBOARD_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@router.get("/app", response_class=HTMLResponse)
@router.get("/app/{path:path}", response_class=HTMLResponse)
async def dashboard(request: Request, path: str = ""):
    dist = request.app.state.dashboard_dist
    index = dist / "index.html"
    if not index.is_file():
        return HTMLResponse("Dashboard not built. Run `npm run build` in frontend/.", status_code=503)
    asset = (dist / path).resolve()
    # Built files (scripts, styles, icons) are served as-is; every other path is an app route.
    if path and asset.is_file() and asset.is_relative_to(dist.resolve()):
        response = FileResponse(asset)
        if path.startswith("assets/"):
            # Vite puts a content hash in these file names, so they never change.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response = FileResponse(index)
        response.headers["Cache-Control"] = "no-cache"
    # Games run in a frame inside the dashboard, with no network access of their own.
    response.headers["Content-Security-Policy"] = GAME_CSP if path.startswith("games/") else DASHBOARD_CSP
    return response
