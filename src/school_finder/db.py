"""Postgres access: schools, extracted facts with provenance, and vector search."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import settings
from .models import School
from .query import SchoolQuery, build_search_sql, build_stats_sql


@contextmanager
def connect(url: str | None = None):
    with psycopg.connect(url or settings.database_url, row_factory=dict_row) as conn:
        try:
            from pgvector.psycopg import register_vector

            register_vector(conn)
        except Exception:  # extension not created yet
            pass
        yield conn


def apply_schema(conn) -> None:
    """(Re)apply db/schema.sql. Idempotent: adds new columns, rebuilds the view."""
    from pathlib import Path

    conn.execute((Path(__file__).resolve().parents[2] / "db" / "schema.sql").read_text())
    conn.commit()


def upsert_schools(conn, schools: Iterable[School]) -> int:
    rows = [s.model_dump() for s in schools]
    if not rows:
        return 0
    cols = list(rows[0].keys())
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in {"ppin", "website"})
    sql = (
        f"INSERT INTO schools ({', '.join(cols)}) VALUES ({', '.join('%(' + c + ')s' for c in cols)}) "
        f"ON CONFLICT (ppin) DO UPDATE SET {updates}, updated_at = now()"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def set_website(conn, ppin: str, url: str) -> None:
    conn.execute("UPDATE schools SET website = %s WHERE ppin = %s", (url, ppin))


def add_fact(conn, ppin: str, field: str, value: dict, source_url: str, quote: str,
             verified: bool, model: str | None) -> None:
    conn.execute(
        "INSERT INTO school_facts (ppin, field, value_json, source_url, quote, verified, model) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (ppin, field, json.dumps(value), source_url, quote, verified, model),
    )


# Rough centers for common places; anything else falls back to the average location
# of loaded schools in that city.
PLACES = {
    "san jose": (37.3382, -121.8863),
    "palo alto": (37.4419, -122.1430),
    "san francisco": (37.7749, -122.4194),
    "oakland": (37.8044, -122.2712),
    "cupertino": (37.3230, -122.0322),
    "santa clara": (37.3541, -121.9552),
    "sunnyvale": (37.3688, -122.0363),
    "mountain view": (37.3861, -122.0839),
}


def resolve_place(conn, place: str) -> tuple[float, float] | None:
    key = place.lower().split(",")[0].strip()
    if key in PLACES:
        return PLACES[key]
    row = conn.execute(
        "SELECT avg(lat) AS lat, avg(lon) AS lon FROM schools WHERE lower(city) = %s "
        "AND lat IS NOT NULL", (key,)).fetchone()
    if row and row["lat"] is not None:
        return float(row["lat"]), float(row["lon"])
    return None


def run_search(conn, q: SchoolQuery) -> dict[str, Any]:
    """Run a SchoolQuery. Returns rows, total matches and how the place was resolved."""
    center = None
    if q.place:
        center = resolve_place(conn, q.place)
        if center is None:
            return {"error": f"Unknown place '{q.place}'. Try a city that has schools loaded, "
                             "or use `cities` to filter by city name.", "rows": [], "total": 0}
    sql, params = build_search_sql(q, center)
    rows = list(conn.execute(sql, params))
    total = rows[0].pop("total") if rows else 0
    for r in rows[1:]:
        r.pop("total", None)
    return {"rows": rows, "total": total, "center": center}


def run_stats(conn, q: SchoolQuery, group_by: str) -> dict[str, Any]:
    center = resolve_place(conn, q.place) if q.place else None
    if q.place and center is None:
        return {"error": f"Unknown place '{q.place}'", "rows": []}
    sql, params = build_stats_sql(q, group_by, center)  # type: ignore[arg-type]
    return {"rows": list(conn.execute(sql, params)), "group_by": group_by}


def get_school(conn, ppin: str) -> dict[str, Any] | None:
    school = conn.execute("SELECT * FROM school_summary WHERE ppin = %s", (ppin,)).fetchone()
    if not school:
        return None
    school["facts"] = list(conn.execute(
        "SELECT field, value_json, source_url, quote, verified, extracted_at "
        "FROM school_facts WHERE ppin = %s ORDER BY extracted_at DESC", (ppin,)))
    return school


def replace_chunks(conn, ppin: str, url: str, chunks: Sequence[str], vectors: Sequence) -> None:
    conn.execute("DELETE FROM page_chunks WHERE ppin = %s AND url = %s", (ppin, url))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO page_chunks (ppin, url, chunk, embedding) VALUES (%s, %s, %s, %s)",
            [(ppin, url, c, v) for c, v in zip(chunks, vectors, strict=True)],
        )


def semantic_search(conn, query_vector, ppins: Sequence[str] | None = None,
                    limit: int = 8) -> list[dict[str, Any]]:
    filt = "WHERE c.ppin = ANY(%(ppins)s)" if ppins else ""
    return list(conn.execute(
        f"""SELECT c.ppin, s.name, c.url, c.chunk,
                   1 - (c.embedding <=> %(q)s) AS similarity
            FROM page_chunks c JOIN schools s USING (ppin) {filt}
            ORDER BY c.embedding <=> %(q)s LIMIT %(limit)s""",
        {"q": query_vector, "ppins": list(ppins or []), "limit": limit},
    ))
