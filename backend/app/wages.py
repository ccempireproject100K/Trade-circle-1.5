"""Government wage data: what employees in each trade earn, by area, from the BLS OEWS survey.

The table is built by scripts/build_wages.py. A member's ZIP code (or city) is
matched to its BLS metro or non-metro area; where BLS publishes nothing for an
occupation there, or the ZIP can't be matched (Connecticut ZIPs, for now), the
statewide figure is shown and labeled as statewide. These are employee wages
only, never what contractors charge customers.
"""
import gzip
import json
from functools import lru_cache

from . import geo

COLUMNS = ("employment", "mean", "p10", "p25", "median", "p75", "p90")


@lru_cache(maxsize=1)
def table() -> dict:
    with gzip.open(geo.DATA / "wages.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=2048)
def _nearest_zip(lat: float, lon: float, state: str) -> str | None:
    """For a city, the ZIP whose center is closest, within the same state."""
    best, found = None, None
    for z, (zlat, zlon, zstate) in geo._zips().items():
        if zstate != state:
            continue
        d = (zlat - lat) ** 2 + (zlon - lon) ** 2
        if best is None or d < best:
            best, found = d, z
    return found


def _row(values: list) -> dict | None:
    row = dict(zip(COLUMNS, values))
    if row["mean"] is None and row["median"] is None:
        return None
    # "#" is how BLS marks $115 an hour or more.
    return {k: (None if v == "#" else v) for k, v in row.items()} | {"capped": [k for k, v in row.items() if v == "#"]}


def lookup(place: dict, trade: str) -> dict:
    """Wages for a trade around a resolved place ({zip?, state, lat, lon})."""
    t = table()
    state = place.get("state")
    zip_code = place.get("zip") or (_nearest_zip(place["lat"], place["lon"], state) if state else None)
    area_code = t["zip_area"].get(zip_code) if zip_code else None
    area = t["areas"].get(area_code) if area_code else None
    area_rows = t["data"].get(area_code, {}) if area_code else {}
    state_rows = t["states"].get(state, {}) if state else {}
    occupations = []
    for soc in t["trades"].get(trade, []):
        row, where = None, None
        if soc in area_rows:
            row, where = _row(area_rows[soc]), "area"
        if row is None and soc in state_rows:
            row, where = _row(state_rows[soc]), "state"
        if row is not None:
            occupations.append({"code": soc, "title": t["occupations"][soc], "where": where, **row})
    return {
        "period": t["period"],
        "source": t["source"],
        "source_url": t["source_url"],
        "area": area["title"] if area else None,
        "state": state,
        "occupations": occupations,
        "note": "What employers report paying employees, in dollars per hour. Not what contractors charge customers.",
    }
