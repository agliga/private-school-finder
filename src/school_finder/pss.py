"""Load the NCES Private School Survey (PSS) public-use CSV.

Download the latest public-use CSV from https://nces.ed.gov/surveys/pss/pssdata.asp
and put it in data/raw/. Column names carry a year suffix in some releases
(e.g. LATITUDE22), so columns are matched by prefix. Check the codebook for the
release you download and adjust COLUMN_PREFIXES / code maps if anything differs.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from pathlib import Path

from .models import School

COLUMN_PREFIXES = {
    "ppin": "PPIN",
    "name": "PINST",
    "address": "PADDRS",
    "city": "PCITY",
    "state": "PSTABB",
    "zip": "PZIP",
    "level": "LEVEL",            # see LEVEL_PREFERENCE
    "typology": "TYPOLOGY",
    "relig": "RELIG",
    "orient": "ORIENT",
    "enrollment": "NUMSTUDS",
    "lat": "LATITUDE",
    "lon": "LONGITUDE",
}

# Newer releases add LEVEL2/3/4 (2021-22 uses LEVEL4); prefer the newest one present.
LEVEL_PREFERENCE = ["LEVEL4", "LEVEL3", "LEVEL2", "LEVEL"]
LEVEL_CODES = {"1": "elementary", "2": "secondary", "3": "combined"}
RELIG_CODES = {"1": "catholic", "2": "other_religious", "3": "nonsectarian"}

# ORIENT codes from the 2021-22 PSS public-use user's manual (NCES 2024-011).
# Older releases numbered these differently; check the codebook before loading one.
ORIENT_CODES: dict[str, str | None] = {
    "1": "Roman Catholic", "2": "African Methodist Episcopal", "3": "Amish",
    "4": "Assembly of God", "5": "Baptist", "6": "Brethren", "7": "Calvinist",
    "8": "Christian (no specific denomination)", "9": "Church of Christ",
    "10": "Church of God", "11": "Church of God in Christ", "12": "Church of the Nazarene",
    "13": "Disciples of Christ", "14": "Episcopal", "15": "Friends", "16": "Greek Orthodox",
    "17": "Islamic", "18": "Jewish", "19": "Latter Day Saints",
    "20": "Lutheran Church - Missouri Synod", "21": "Evangelical Lutheran Church in America",
    "22": "Wisconsin Evangelical Lutheran Synod", "23": "Other Lutheran", "24": "Mennonite",
    "25": "Methodist", "26": "Pentecostal", "27": "Presbyterian", "28": "Seventh-day Adventist",
    "29": "Other religious", "30": None,  # 30 = Nonsectarian
}

TYPOLOGY_CODES = {
    "1": "catholic_parochial", "2": "catholic_diocesan", "3": "catholic_private",
    "4": "conservative_christian", "5": "religious_affiliated", "6": "religious_unaffiliated",
    "7": "nonsectarian_regular", "8": "nonsectarian_special_emphasis",
    "9": "nonsectarian_special_education",
}


def resolve_columns(header: Iterable[str]) -> dict[str, str]:
    """Map our field names to the actual CSV column names by prefix."""
    cols = {h.strip().upper(): h for h in header}
    resolved: dict[str, str] = {}
    level = next((cols[c] for c in LEVEL_PREFERENCE if c in cols), None)
    if level:
        resolved["level"] = level
    for field, prefix in COLUMN_PREFIXES.items():
        if field in resolved:
            continue
        exact = cols.get(prefix)
        if exact:
            resolved[field] = exact
            continue
        matches = sorted(c for c in cols if c.startswith(prefix))
        if matches:
            resolved[field] = cols[matches[0]]
    missing = {"ppin", "name"} - resolved.keys()
    if missing:
        raise ValueError(f"PSS file is missing required columns: {sorted(missing)}")
    return resolved


def _num(value: str | None, cast=float):
    if value is None:
        return None
    value = value.strip()
    if not value or value in {"-1", "-2", "-3", "-9", "."}:
        return None
    try:
        return cast(value)
    except ValueError:
        return None


def parse_row(row: dict[str, str], cols: dict[str, str], pss_year: str | None) -> School:
    get = lambda f: (row.get(cols[f]) or "").strip() if f in cols else ""  # noqa: E731
    relig = RELIG_CODES.get(get("relig"))
    orient = ORIENT_CODES.get(get("orient").lstrip("0"))
    return School(
        ppin=get("ppin"),
        name=get("name").title() if get("name").isupper() else get("name"),
        address=get("address") or None,
        city=(get("city").title() or None),
        state=get("state") or None,
        zip=get("zip")[:5] or None,
        lat=_num(get("lat")),
        lon=_num(get("lon")),
        religious_group=relig,
        affiliation=orient or ("Roman Catholic" if relig == "catholic" else None),
        level=LEVEL_CODES.get(get("level")),
        typology=TYPOLOGY_CODES.get(get("typology")),
        enrollment=_num(get("enrollment"), lambda v: int(float(v))),
        pss_year=pss_year,
    )


def read_pss(path: Path, state: str | None = None, pss_year: str | None = None) -> Iterator[School]:
    with path.open(newline="", encoding="latin-1") as f:
        reader = csv.DictReader(f)
        cols = resolve_columns(reader.fieldnames or [])
        for row in reader:
            school = parse_row(row, cols, pss_year)
            if state and (school.state or "").upper() != state.upper():
                continue
            yield school
