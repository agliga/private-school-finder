"""Integration tests against a real Postgres + pgvector (skipped if none is running)."""

import json
from pathlib import Path

import numpy as np
import pytest

psycopg = pytest.importorskip("psycopg")

from school_finder import db  # noqa: E402
from school_finder.pss import read_pss  # noqa: E402
from school_finder.tools import run_tool  # noqa: E402

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
CSV = Path(__file__).parent / "fixtures" / "pss_sample.csv"


@pytest.fixture
def conn():
    try:
        with db.connect() as c:
            c.execute(SCHEMA.read_text())
            c.execute("TRUNCATE schools CASCADE")
            from pgvector.psycopg import register_vector  # after CREATE EXTENSION

            register_vector(c)
            yield c
            c.rollback()
    except psycopg.OperationalError:
        pytest.skip("Postgres not available")


def test_search_filters_and_provenance(conn):
    db.upsert_schools(conn, read_pss(CSV, state="CA"))
    db.add_fact(conn, "X0000001", "tuition_max", {"amount": 38500}, "https://example-prep.test/t",
                "Tuition is $38,500", True, "stub")
    db.add_fact(conn, "X0000002", "tuition_max", {"amount": 99}, "https://x.test", "made up",
                False, "stub")  # unverified: must not count

    near = db.search_schools(conn, 37.3382, -121.8863, radius_miles=10)
    assert {r["ppin"] for r in near} == {"X0000001", "X0000002"}

    cheap = db.search_schools(conn, 37.3382, -121.8863, radius_miles=10, max_tuition=40000)
    assert [r["ppin"] for r in cheap] == ["X0000001"]

    catholic = json.loads(run_tool(conn, "search_schools",
                                   {"place": "San Jose", "religious_group": "catholic"}))
    assert [r["ppin"] for r in catholic] == ["X0000002"]

    detail = db.get_school(conn, "X0000001")
    assert detail["facts"][0]["quote"] == "Tuition is $38,500"


def test_semantic_search(conn):
    db.upsert_schools(conn, read_pss(CSV, state="CA"))
    a, b = np.zeros(384, dtype=np.float32), np.zeros(384, dtype=np.float32)
    a[0], b[1] = 1, 1
    db.replace_chunks(conn, "X0000001", "https://example-prep.test/robotics",
                      ["Our robotics team"], [a])
    db.replace_chunks(conn, "X0000002", "https://st-example.test/arts", ["Fine arts"], [b])
    hits = db.semantic_search(conn, a, limit=1)
    assert hits[0]["ppin"] == "X0000001"
