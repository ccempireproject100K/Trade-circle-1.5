"""Build the government wage table from the Bureau of Labor Statistics OEWS survey.

Download from https://www.bls.gov/oes/tables.htm (public-domain data):
  oesm25ma.zip (metro and non-metro areas: MSA_M2025_dl.xlsx, BOS_M2025_dl.xlsx)
  oesm25st.zip (states: state_M2025_dl.xlsx)
  area_definitions_m2025.xlsx (which counties make up each area)
and the Census ZIP-to-county file tab20_zcta520_county20_natl.txt from
https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
Unzip everything into one folder, then run (needs openpyxl):
  python scripts/build_wages.py <folder> "May 2025"
Re-run each spring when BLS publishes the next year's figures.
"""
import csv
import gzip
import json
import sys
from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "wages.json.gz"

# Our trades and the BLS occupations that match them, most direct first.
TRADE_OCCUPATIONS = {
    "electrician": ["47-2111", "47-3013"],
    "plumber": ["47-2152", "47-3015"],
    "hvac": ["49-9021"],
    "roofer": ["47-2181"],
    "carpenter": ["47-2031"],
    "painter": ["47-2141"],
    "landscaper": ["37-3011"],
    "mason": ["47-2021", "47-2051"],
    "flooring": ["47-2044", "47-2042", "47-2041"],
    "general_contractor": ["47-1011", "11-9021"],
    "handyman": ["49-9071"],
    "other": ["47-2061"],
}
WANTED = {soc for socs in TRADE_OCCUPATIONS.values() for soc in socs}
# Hourly figures in the order stored: employment, mean, 10th, 25th, median, 75th, 90th percentile.
COLUMNS = ("TOT_EMP", "H_MEAN", "H_PCT10", "H_PCT25", "H_MEDIAN", "H_PCT75", "H_PCT90")


def _value(v):
    """BLS marks figures it can't publish with "*" or "**", and wages of $115/hour or more with "#"."""
    if v in (None, "", "*", "**"):
        return None
    if v == "#":
        return "#"
    return float(v) if not isinstance(v, (int, float)) else v


def _sheet(path: Path):
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).upper() for h in next(rows)]
    for r in rows:
        yield dict(zip(header, r))


def main(folder: str, period: str) -> None:
    src = Path(folder)
    areas, data, titles = {}, {}, {}
    for name in ("MSA_M2025_dl.xlsx", "BOS_M2025_dl.xlsx"):
        for r in _sheet(next(src.rglob(name))):
            if r["OCC_CODE"] not in WANTED:
                continue
            code = str(r["AREA"])
            areas[code] = {"title": r["AREA_TITLE"], "state": r["PRIM_STATE"]}
            titles[r["OCC_CODE"]] = r["OCC_TITLE"]
            data.setdefault(code, {})[r["OCC_CODE"]] = [_value(r[c]) for c in COLUMNS]
    states = {}
    for r in _sheet(next(src.rglob("state_M2025_dl.xlsx"))):
        if r["OCC_CODE"] in WANTED:
            states.setdefault(r["PRIM_STATE"], {})[r["OCC_CODE"]] = [_value(r[c]) for c in COLUMNS]
    county_area = {}
    for r in _sheet(next(src.rglob("area_definitions_m2025.xlsx"))):
        county_area[f"{r['FIPS CODE']}{r['COUNTY CODE']}"] = str(r["MAY 2025 AREA CODE"])
    # Each ZIP's county: the one holding most of its land.
    zip_county, best = {}, {}
    with next(src.rglob("tab20_zcta520_county20_natl.txt")).open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter="|"):
            z, county, part = r["GEOID_ZCTA5_20"], r["GEOID_COUNTY_20"], int(r["AREALAND_PART"] or 0)
            if z and county and part > best.get(z, -1):
                best[z], zip_county[z] = part, county
    out = {
        "period": period,
        "source": "U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics",
        "source_url": "https://www.bls.gov/oes/",
        "columns": ["employment", "mean", "p10", "p25", "median", "p75", "p90"],
        "trades": TRADE_OCCUPATIONS,
        "occupations": titles,
        "areas": areas,
        "data": data,
        "states": states,
        "county_area": county_area,
        "zip_area": {z: county_area[c] for z, c in zip_county.items() if c in county_area},
    }
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{len(areas)} areas, {len(states)} states, {len(titles)} occupations, {len(out['zip_area'])} ZIPs -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "May 2025")
