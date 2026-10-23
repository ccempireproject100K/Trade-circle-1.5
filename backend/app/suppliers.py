"""Supplier directory rules: platform facts, verification wording, seeding and removal.

Directory facts come from the platform and say where they came from. Member
experiences are posts, kept apart and labeled as opinions. Starter listings
get no preferred placement, and nothing is called "verified" or "trusted":
the label states exactly what was checked and what wasn't.
"""
import json
import re
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .deps import now

SEED_FILE = Path(__file__).parent / "data" / "suppliers_seed.json"
REMOVED_TEXT = "[supplier]"
NOT_CHECKED = "Not checked: prices, stock, service quality, or any branch's details."


def domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def verification_text(sources: list[dict]) -> list[str]:
    lines = []
    for s in sources:
        checked = date.fromisoformat(s["checked_on"]).strftime("%b %-d, %Y")
        lines.append(f"Checked {checked}: {s['method']} ({domain(s['url'])}). Confirms only the details shown here.")
    return lines + [NOT_CHECKED]


async def seed(db) -> int:
    """Add the starter listings that aren't there yet (matched by website). Returns how many were added."""
    data = json.loads(SEED_FILE.read_text())
    added = 0
    for entry in data["suppliers"]:
        if await db.suppliers.find_one({"website": entry["website"]}, {"_id": 1}):
            continue
        await db.suppliers.insert_one(
            {
                "_id": uuid.uuid4().hex,
                **entry,
                "locations": [],
                "origin": "starter",
                "status": "active",
                "created_at": now(),
            }
        )
        added += 1
    return added


# --- removal ---


def identifiers(supplier: dict, aliases: list[str]) -> list[str]:
    """Strings that identify the supplier: its name, website address, and any aliases a moderator adds."""
    found = {supplier.get("name") or "", *aliases}
    if supplier.get("website"):
        host = domain(supplier["website"])
        found |= {host, host.split(".")[0]}
    for loc in supplier.get("locations", []):
        if loc.get("address"):
            found.add(loc["address"])
            # People say "the yard on Industrial Blvd" more often than the full street address.
            found.add(re.sub(r"^\d+[A-Za-z]?\s+", "", loc["address"]))
    # Longest first, so "ABC Supply Co." is replaced before "ABC Supply".
    return sorted((s.strip() for s in found if s and len(s.strip()) >= 3), key=len, reverse=True)


def scrub(text: str, names: list[str]) -> tuple[str, bool]:
    changed = False
    for name in names:
        pattern = re.compile(re.escape(name), re.I)
        if pattern.search(text):
            text, changed = pattern.sub(REMOVED_TEXT, text), True
    return text, changed


def _scrub_fields(fields: dict, names: list[str]) -> tuple[dict, bool]:
    changed = False
    out = {}
    for key, value in fields.items():
        if isinstance(value, str):
            value, hit = scrub(value, names)
            changed = changed or hit
        out[key] = value
    return out, changed


async def remove(db, supplier: dict, aliases: list[str], flag) -> dict:
    """Take down a listing at the business's verified request.

    The listing and its public details go; member posts stay, with the
    supplier's name, website and addresses replaced by "[supplier]" and their
    photos hidden (photos can show signs and logos). Every changed post and
    comment is flagged for a moderator, because automatic replacement can miss
    things like nicknames or descriptions that still point to the business.
    """
    names = identifiers(supplier, aliases)
    stamp = now()
    await db.suppliers.update_one(
        {"_id": supplier["_id"]},
        {
            "$set": {"status": "removed", "removed_at": stamp, "name": None},
            "$unset": {k: "" for k in ("website", "offers", "branch_note", "locations", "delivery", "business_account", "sources", "trades", "categories", "ships_to", "coverage")},
        },
    )
    name_pattern = {"$regex": "|".join(re.escape(n) for n in names), "$options": "i"}
    posts = await db.posts.find(
        {"$or": [{"supplier_id": supplier["_id"]}, {"title": name_pattern}, {"body": name_pattern}, {"fields.suggested_name": name_pattern}, {"fields.suggested_website": name_pattern}]}
    ).to_list(None)
    changed_posts = 0
    for post in posts:
        title, _ = scrub(post.get("title", ""), names)
        body, _ = scrub(post.get("body", ""), names)
        fields, _ = _scrub_fields(post.get("fields", {}), names)
        update = {"title": title, "body": body, "fields": fields, "photos_hidden": bool(post.get("photos"))}
        await db.posts.update_one({"_id": post["_id"]}, {"$set": update})
        changed_posts += 1
        await flag(db, "post", post["_id"], "anonymization_review",
                   "Supplier removed at the business's request. Check that nothing left in this post still identifies them"
                   + ("; photos were hidden and may show signs or logos." if update.get("photos_hidden") else "."))
    comments = await db.comments.find({"$or": [{"post_id": {"$in": [p["_id"] for p in posts]}}, {"body": name_pattern}]}).to_list(None)
    changed_comments = 0
    for c in comments:
        body, hit = scrub(c["body"], names)
        if hit:
            await db.comments.update_one({"_id": c["_id"]}, {"$set": {"body": body}})
            changed_comments += 1
            await flag(db, "comment", c["_id"], "anonymization_review", "Supplier removed at the business's request. Check this reply for anything still identifying them.")
    return {"posts": changed_posts, "comments": changed_comments, "names_replaced": names}
