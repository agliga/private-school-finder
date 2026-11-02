"""Turn extracted facts into categories people can filter on."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"

TUITION_BANDS = [
    (0, 15_000, "under $15k"),
    (15_000, 30_000, "$15k-$30k"),
    (30_000, 45_000, "$30k-$45k"),
    (45_000, float("inf"), "$45k+"),
]


def tuition_band(amount: float | None) -> str:
    if amount is None:
        return "not published"
    for lo, hi, label in TUITION_BANDS:
        if lo <= amount < hi:
            return label
    return "not published"


def normalize_college(name: str) -> str:
    name = name.lower().replace("&", "and")
    name = re.sub(r"\(.*?\)|[^a-z0-9 ]", " ", name)
    name = re.sub(r"\b(the|of|at)\b", " ", name)
    return re.sub(r"\s+", " ", name).strip()


@lru_cache
def selective_colleges(path: Path = DATA / "selective_colleges.txt") -> frozenset[str]:
    lines = path.read_text().splitlines()
    return frozenset(normalize_college(x) for x in lines if x.strip() and not x.startswith("#"))


def college_outcome_score(colleges: list[str], selective: frozenset[str] | None = None) -> float | None:
    """Share (0-1) of listed colleges that are on the selective list.

    A rough, transparent signal: schools publish lists differently (enrolled vs admitted,
    one year vs several), so the score is shown with its source, never as a ranking of truth.
    """
    if not colleges:
        return None
    selective = selective if selective is not None else selective_colleges()
    names = {normalize_college(c) for c in colleges if c.strip()}
    if not names:
        return None
    hits = sum(1 for n in names if n in selective)
    return round(hits / len(names), 3)
