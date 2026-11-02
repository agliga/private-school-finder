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
    "level": "LEVEL",
    "relig": "RELIG",
    "orient": "ORIENT",
    "enrollment": "NUMSTUDS",
    "lat": "LATITUDE",
    "lon": "LONGITUDE",
}

LEVEL_CODES = {"1": "elementary", "2": "secondary", "3": "combined"}
RELIG_CODES = {"1": "catholic", "2": "other_religious", "3": "nonsectarian"}

# Detailed ORIENT codes vary by release. Fill this from the codebook you download;
# unknown codes fall back to the RELIG group, and the agent can still extract the
# affiliation from the school's own site.
ORIENT_CODES: dict[str, str] = {}


def resolve_columns(header: Iterable[str]) -> dict[str, str]:
    """Map our field names to the actual CSV column names by prefix."""
    cols = {h.strip().upper(): h for h in header}
    resolved: dict[str, str] = {}
    for field, prefix in COLUMN_PREFIXES.items():
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
    orient = ORIENT_CODES.get(get("orient"))
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
