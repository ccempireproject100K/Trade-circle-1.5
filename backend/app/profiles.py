"""Profile rules: slugs, layout reflow, badges and the two public layers."""
import re
import uuid
from datetime import date

# Sections of the full profile, in default order. The contractor drags these
# into their own order; the landing page is always the fixed scannable layer.
SECTIONS = ("about", "portfolio", "projects", "licenses", "insurance", "service_area", "quote")
FEATURED_PROJECTS = 6
LANDING_PORTFOLIO_COUNT = 6


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50].strip("-") or "pro"


async def unique_slug(db, business_name: str) -> str:
    base = slugify(business_name)
    slug = base
    while await db.profiles.find_one({"slug": slug}, {"_id": 1}):
        slug = f"{base}-{uuid.uuid4().hex[:4]}"
    return slug


def reflow_layout(requested: list[str] | None) -> list[str]:
    """Keep known sections in the requested order, drop unknowns and repeats, append the rest."""
    ordered: list[str] = []
    for section in requested or []:
        if section in SECTIONS and section not in ordered:
            ordered.append(section)
    return ordered + [s for s in SECTIONS if s not in ordered]


def insurance_status(insurance: dict | None, today: date) -> str:
    if not insurance:
        return "none"
    if date.fromisoformat(insurance["expires_on"]) < today:
        return "expired"
    return "verified" if insurance.get("verified") else "pending"


def compute_badges(profile: dict, today: date, banner_days: int) -> dict:
    badges = []
    celebrations = []
    for lic in profile.get("licenses", []):
        expires = date.fromisoformat(lic["expires_on"])
        if expires < today:
            badges.append({"type": "cert_lapsed", "label": f"{lic['name']} lapsed"})
            continue
        renewed = lic.get("renewed_on")
        if renewed and 0 <= (today - date.fromisoformat(renewed)).days < banner_days:
            celebrations.append({"type": "recertified", "label": f"Re-certified: {lic['name']}"})

    status = insurance_status(profile.get("insurance"), today)
    badges.append({"type": f"insurance_{status}", "label": _INSURANCE_LABELS[status]})
    if not profile.get("verified"):
        badges.insert(0, {"type": "unverified", "label": "Unverified"})
    return {"verified": bool(profile.get("verified")), "badges": badges, "celebrations": celebrations}


_INSURANCE_LABELS = {
    "none": "No insurance on file",
    "pending": "Insurance pending review",
    "verified": "Insured",
    "expired": "Insurance expired",
}


DEFAULT_BRAND_COLOR = "#4A2F1B"


def text_color_on(hex_color: str) -> str:
    """Black or white, whichever reads better on the brand color (WCAG relative luminance)."""
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#111111" if luminance > 0.179 else "#FFFFFF"


def call_links(profile: dict) -> dict:
    links = {}
    if profile.get("phone"):
        links["tel"] = f"tel:{profile['phone']}"
    if profile.get("facetime"):
        # The client shows this button only on Apple devices.
        links["facetime"] = f"facetime:{profile['facetime']}"
    return links


def _portfolio_view(item: dict) -> dict:
    return {
        "id": item["_id"],
        "image_url": item["image_url"],
        # Uploaded photos have a small square version for grids; linked ones don't.
        "thumb_url": item.get("thumb_url") or item["image_url"],
        "caption": item.get("caption", ""),
        "trade_tag": item.get("trade_tag"),
        "taken_on": item.get("taken_on"),
    }


def landing_view(profile: dict, portfolio: list[dict], today: date, banner_days: int) -> dict:
    """Layer one: the scannable page."""
    return {
        "slug": profile["slug"],
        "business_name": profile["business_name"],
        "tagline": profile.get("tagline", ""),
        "trade": profile["trade"],
        "city": profile["city"],
        "brand_color": profile.get("brand_color"),
        "call": call_links(profile),
        **compute_badges(profile, today, banner_days),
        "portfolio": [_portfolio_view(p) for p in portfolio[:LANDING_PORTFOLIO_COUNT]],
        "quote_enabled": True,
    }


def _project_view(post: dict) -> dict:
    photos = post.get("photos", [])
    # Finished photos first: they show the result.
    ordered = [p for p in photos if p.get("group") == "after"] + [p for p in photos if p.get("group") != "after"]
    return {
        "id": post["_id"],
        "title": post.get("title") or "Project",
        "job": post.get("fields", {}).get("job", ""),
        "learned": post.get("fields", {}).get("learned", ""),
        "photos": [{"thumb_url": p["thumb_url"], "image_url": p["image_url"]} for p in ordered[:3]],
        "trade_tags": post.get("trade_tags", []),
    }


def full_view(profile: dict, portfolio: list[dict], today: date, banner_days: int, projects: list[dict] | None = None) -> dict:
    """Layer two: everything public, in the contractor's section order."""
    view = landing_view(profile, portfolio, today, banner_days)
    insurance = profile.get("insurance")
    view.update(
        {
            "about": profile.get("about", ""),
            "service_area": profile.get("service_area", ""),
            "layout": reflow_layout(profile.get("layout")),
            "licenses": [
                {
                    "name": lic["name"],
                    "issuer": lic.get("issuer", ""),
                    "expires_on": lic["expires_on"],
                    "lapsed": date.fromisoformat(lic["expires_on"]) < today,
                }
                for lic in profile.get("licenses", [])
            ],
            "insurance": {
                "status": insurance_status(insurance, today),
                "carrier": insurance["carrier"] if insurance else None,
                "expires_on": insurance["expires_on"] if insurance else None,
            },
            "portfolio": [_portfolio_view(p) for p in portfolio],
            # Walkthroughs the member chose to feature, as portfolio content.
            "projects": [_project_view(p) for p in projects or []],
        }
    )
    return view
