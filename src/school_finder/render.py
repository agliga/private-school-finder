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


def _clock(hhmm: str | None) -> str:
    """'15:10' -> '3:10p'."""
    if not hhmm:
        return "-"
    h, m = (int(x) for x in hhmm[:5].split(":"))
    return f"{(h % 12) or 12}:{m:02d}{'a' if h < 12 else 'p'}"


def _day(iso: str | None) -> str:
    if not iso:
        return "-"
    from datetime import date

    return date.fromisoformat(iso).strftime("%b %-d")


def _miles(r: dict) -> str:
    if r.get("drive_miles") is not None:
        return f"{float(r['drive_miles']):.1f}"
    if r.get("miles") is not None:
        return f"~{float(r['miles']):.1f}"
    return "-"


def _drive(minutes, leave: str | None) -> str:
    if minutes is None:
        return "-"
    return f"{int(minutes)} min" + (f" ({_clock(leave)})" if leave else "")


def _time_cell(r: dict, key: str, used: str, assumed: str) -> str:
    if r.get(key):
        return _clock(r[key])
    if r.get(used):
        return _clock(r[used]) + ("*" if r.get(assumed) else "")
    return "-"


def school_columns(rows: Sequence[dict]) -> list[tuple[str, Any]]:
    travel = any(k in r for r in rows for k in ("am_minutes", "drive_miles", "am_depart"))
    cols: list[tuple[str, Any]] = [
        ("#", None),
        ("School", lambda r: r["name"]),
        ("Address", lambda r: r.get("address") or "-"),
        ("City", lambda r: r.get("city") or "-"),
        ("Level", lambda r: LEVEL_LABEL.get(r.get("level") or "", "-")),
        ("Affiliation", _affiliation),
        ("Students", lambda r: f"{r['enrollment']:,}" if r.get("enrollment") is not None else "-"),
    ]
    if any(r.get("miles") is not None or r.get("drive_miles") is not None for r in rows):
        cols.append(("Miles", _miles))
    if travel:
        cols += [
            ("AM drive (leave)", lambda r: _drive(r.get("am_minutes"), r.get("am_depart"))),
            ("Start", lambda r: _time_cell(r, "start_time", "start_time_used", "start_assumed")),
            ("PM drive (leave)", lambda r: _drive(r.get("pm_minutes"), r.get("pm_depart"))),
            ("End", lambda r: _time_cell(r, "end_time", "end_time_used", "end_assumed")),
        ]
    elif any(r.get("start_time") or r.get("end_time") for r in rows):
        cols += [("Start", lambda r: _clock(r.get("start_time"))),
                 ("End", lambda r: _clock(r.get("end_time")))]
    if any(r.get("first_day") or r.get("last_day") for r in rows) or travel:
        cols += [("First day", lambda r: _day(r.get("first_day"))),
                 ("Last day", lambda r: _day(r.get("last_day")))]
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
    out = table([h for h, _ in cols], body)
    notes = []
    if any(r.get("miles") is not None and r.get("drive_miles") is None for r in rows):
        notes.append("~ straight-line miles (no drive route computed)")
    if any(r.get("start_assumed") or r.get("end_assumed") for r in rows):
        notes.append("* school hasn't published this time (or isn't enriched yet); default used")
    return out + ("\n\n" + "\n".join(notes) if notes else "")


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
    fields: list[str] = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow({k: float(v) if isinstance(v, Decimal) else v for k, v in r.items()})
    return buf.getvalue()
