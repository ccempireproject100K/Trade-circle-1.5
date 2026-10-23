"""Build the ZIP and city coordinate tables from the Census Bureau's public Gazetteer files.

Download 2024_Gaz_zcta_national.txt and 2024_Gaz_place_national.txt from
https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
and tab20_zcta520_county20_natl.txt (ZIP-to-county relationships, for each ZIP's state) from
https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
then run:  python scripts/build_geo.py <folder with the .txt files>
Public-domain data; no paid maps service is needed.
"""
import csv
import gzip
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "data"
SUFFIX = re.compile(
    r"\s+(city and borough|city|town|township|village|borough|municipality|CDP|"
    r"(unified |metropolitan |consolidated )?government|urban county|comunidad|zona urbana)\b.*$",
    re.I,
)


def rows(path: Path):
    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        header = [h.strip() for h in next(reader)]
        for row in reader:
            yield dict(zip(header, (c.strip() for c in row)))


def main(folder: str) -> None:
    src = Path(folder)
    # State of each ZIP: the state holding most of its land area.
    fips_to_usps = {}
    for r in rows(src / "2024_Gaz_place_national.txt"):
        fips_to_usps[r["GEOID"][:2]] = r["USPS"]
    land: dict[str, tuple[int, str]] = {}
    with (src / "tab20_zcta520_county20_natl.txt").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter="|"):
            zcta, county, part = r["GEOID_ZCTA5_20"], r["GEOID_COUNTY_20"], int(r["AREALAND_PART"] or 0)
            if zcta and county and part > land.get(zcta, (-1, ""))[0]:
                land[zcta] = (part, fips_to_usps.get(county[:2], ""))
    zips = {}
    for r in rows(src / "2024_Gaz_zcta_national.txt"):
        zips[r["GEOID"]] = [round(float(r["INTPTLAT"]), 4), round(float(r["INTPTLONG"]), 4), land.get(r["GEOID"], (0, ""))[1]]
    places: dict[str, list] = {}
    incorporated: set[str] = set()
    for r in rows(src / "2024_Gaz_place_national.txt"):
        name = SUFFIX.sub("", r["NAME"]).split("-")[0].strip() if "(balance)" in r["NAME"] else SUFFIX.sub("", r["NAME"]).strip()
        key = f"{name.lower()}|{r['USPS'].lower()}"
        # Prefer incorporated places over census-designated places of the same name.
        if key in places and (key in incorporated or r["FUNCSTAT"] != "A"):
            continue
        places[key] = [round(float(r["INTPTLAT"]), 4), round(float(r["INTPTLONG"]), 4)]
        if r["FUNCSTAT"] == "A":
            incorporated.add(key)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("zips", zips), ("places", places)):
        with gzip.open(OUT / f"{name}.json.gz", "wt", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
    print(f"{len(zips)} ZIP codes, {len(places)} places")


if __name__ == "__main__":
    main(sys.argv[1])
