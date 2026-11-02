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

METERS_PER_MILE = 1609.344


@contextmanager
def connect(url: str | None = None):
    with psycopg.connect(url or settings.database_url, row_factory=dict_row) as conn:
        try:
            from pgvector.psycopg import register_vector

            register_vector(conn)
        except Exception:  # extension not created yet
            pass
        yield conn


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


def search_schools(
    conn,
    lat: float,
    lon: float,
    radius_miles: float = 15,
    religious_group: str | None = None,
    affiliation: str | None = None,
    level: str | None = None,
    max_tuition: float | None = None,
    min_outcome_score: float | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Structured search. Unknown tuition/outcome values are kept unless a filter excludes them."""
    where = ["earth_box(ll_to_earth(%(lat)s, %(lon)s), %(radius)s) @> ll_to_earth(lat, lon)",
             "earth_distance(ll_to_earth(%(lat)s, %(lon)s), ll_to_earth(lat, lon)) <= %(radius)s"]
    params: dict[str, Any] = {"lat": lat, "lon": lon, "radius": radius_miles * METERS_PER_MILE,
                              "limit": limit}
    if religious_group:
        where.append("religious_group = %(religious_group)s")
        params["religious_group"] = religious_group
    if affiliation:
        where.append("affiliation ILIKE %(affiliation)s")
        params["affiliation"] = f"%{affiliation}%"
    if level:
        where.append("level = %(level)s")
        params["level"] = level
    if max_tuition is not None:
        where.append("tuition_max <= %(max_tuition)s")
        params["max_tuition"] = max_tuition
    if min_outcome_score is not None:
        where.append("college_outcome_score >= %(min_score)s")
        params["min_score"] = min_outcome_score
    sql = f"""
        SELECT ppin, name, city, religious_group, affiliation, level, enrollment, website,
               tuition_max, college_outcome_score,
               round((earth_distance(ll_to_earth(%(lat)s, %(lon)s), ll_to_earth(lat, lon))
                      / {METERS_PER_MILE})::numeric, 1) AS miles
        FROM school_summary
        WHERE {' AND '.join(where)}
        ORDER BY miles
        LIMIT %(limit)s"""
    return list(conn.execute(sql, params))


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
