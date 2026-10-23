"""ZIP and city coordinates for distance filters, from public Census Gazetteer data.

Built by scripts/build_geo.py. No paid maps or geocoding service is used, so
lookups are free and work offline. Coordinates are area centers, which is
right for "within 25 miles", not for driving directions.
"""
import gzip
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status

DATA = Path(__file__).parent / "data"
EARTH_MILES = 3958.8
STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
    "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR",
    "PA", "PR", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}


@lru_cache(maxsize=1)
def _zips() -> dict:
    with gzip.open(DATA / "zips.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _places() -> dict:
    with gzip.open(DATA / "places.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def resolve(text: str) -> dict:
    """Turn "78701" or "Austin, TX" into {label, zip?, city?, state?, lat, lon}, or raise 422."""
    text = (text or "").strip()
    if re.fullmatch(r"\d{5}", text):
        point = _zips().get(text)
        if point:
            return {"label": text, "zip": text, "lat": point[0], "lon": point[1], "state": point[2] or None}
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"We don't recognize the ZIP code {text}.")
    match = re.fullmatch(r"(.+?)[,\s]+([A-Za-z]{2})", text)
    if match and match.group(2).upper() in STATES:
        city, state = match.group(1).strip(), match.group(2).upper()
        point = _places().get(f"{city.lower()}|{state.lower()}")
        if point:
            return {"label": f"{city.title()}, {state}", "city": city.title(), "state": state, "lat": point[0], "lon": point[1]}
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"We couldn't find {city.title()}, {state}. Try a ZIP code.")
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, 'Enter a 5-digit ZIP code or "City, ST", like "Austin, TX".')


def miles(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_MILES * math.asin(math.sqrt(h))


def box(center: dict, radius: float) -> dict:
    """A latitude/longitude box around center, used to narrow database queries before exact distances."""
    dlat = radius / 69.0
    dlon = radius / max(69.0 * math.cos(math.radians(center["lat"])), 1e-6)
    return {"lat": {"$gte": center["lat"] - dlat, "$lte": center["lat"] + dlat}, "lon": {"$gte": center["lon"] - dlon, "$lte": center["lon"] + dlon}}


def state_of(point: dict) -> str | None:
    return point.get("state")
