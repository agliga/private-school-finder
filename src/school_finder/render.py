"""Plain-text tables for the terminal (no extra dependencies)."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

LEVEL_LABEL = {"secondary": "High", "elementary": "Elem/Middle", "combined": "K-12/Combined"}
GROUP_LABEL = {"catholic": "Catholic", "other_religious": "Other religious",
               "nonsectarian": "Nonsectarian"}


def _affiliation(r: dict) -> str:
    return r.get("affiliation") or GROUP_LABEL.get(r.get("religious_group") or "", "") or "-"


def _money(v) -> str:
    return f"${float(v):,.0f}" if v is not None else "-"


def school_columns(rows: Sequence[dict]) -> list[tuple[str, Any]]:
    cols: list[tuple[str, Any]] = [
        ("#", None),
        ("School", lambda r: r["name"]),
        ("City", lambda r: r.get("city") or "-"),
        ("Level", lambda r: LEVEL_LABEL.get(r.get("level") or "", "-")),
        ("Affiliation", _affiliation),
        ("Students", lambda r: f"{r['enrollment']:,}" if r.get("enrollment") is not None else "-"),
    ]
    if any(r.get("miles") is not None for r in rows):
        cols.append(("Miles", lambda r: f"{float(r['miles']):.1f}" if r.get("miles") is not None else "-"))
    if any(r.get("tuition_max") is not None for r in rows):
        cols.append(("Tuition", lambda r: _money(r.get("tuition_max"))))
    if any(r.get("college_outcome_score") is not None for r in rows):
        cols.append(("Outcome", lambda r: f"{float(r['college_outcome_score']):.2f}"
                     if r.get("college_outcome_score") is not None else "-"))
    return cols


def table(headers: list[str], body: list[list[str]], max_width: int = 42) -> str:
    body = [[c if len(c) <= max_width else c[: max_width - 1] + "…" for c in row] for row in body]
    widths = [max(len(h), *(len(row[i]) for row in body)) if body else len(h)
              for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True))  # noqa: E731
    out = [line(headers), "  ".join("-" * w for w in widths)]
    out += [line(row) for row in body]
    return "\n".join(out)


def schools_table(rows: Sequence[dict]) -> str:
    cols = school_columns(rows)
    body = [[str(i) if fn is None else str(fn(r)) for (_, fn) in cols]
            for i, r in enumerate(rows, 1)]
    return table([h for h, _ in cols], body)


def stats_table(rows: Sequence[dict], group_by: str) -> str:
    label = {"religious_group": "Religious group", "affiliation": "Affiliation", "city": "City",
             "level": "Level", "typology": "School type"}.get(group_by, group_by)
    fmt = lambda v: GROUP_LABEL.get(v, LEVEL_LABEL.get(v, v.replace("_", " ") if v else "-"))  # noqa: E731
    body = [[fmt(str(r["value"])), str(r["schools"]),
             f"{int(r['students']):,}" if r.get("students") is not None else "-"] for r in rows]
    total = sum(int(r["schools"]) for r in rows)
    return table([label, "Schools", "Students"], body) + f"\n\nTotal: {total} schools"


def to_csv(rows: Sequence[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    for r in rows:
        w.writerow({k: float(v) if isinstance(v, Decimal) else v for k, v in r.items()})
    return buf.getvalue()
