"""Integration tests against a real Postgres + pgvector (skipped if none is running)."""

import json
from pathlib import Path

import numpy as np
import pytest

psycopg = pytest.importorskip("psycopg")

from school_finder import db  # noqa: E402
from school_finder.pss import read_pss  # noqa: E402
from school_finder.query import SchoolQuery  # noqa: E402
from school_finder.tools import run_tool  # noqa: E402

CSV = Path(__file__).parent / "fixtures" / "pss_sample.csv"


@pytest.fixture
def conn():
    try:
        with db.connect() as c:
            db.apply_schema(c)
            db.apply_schema(c)  # must be safe to re-run
            c.execute("TRUNCATE schools CASCADE")
            from pgvector.psycopg import register_vector  # after CREATE EXTENSION

            register_vector(c)
            db.upsert_schools(c, read_pss(CSV, state="CA"))
            yield c
            c.rollback()
    except psycopg.OperationalError:
        pytest.skip("Postgres not available")


def names(res):
    return [r["name"] for r in res["rows"]]


def test_all_catholic_schools(conn):
    res = db.run_search(conn, SchoolQuery(religious_groups=["catholic"], limit=500))
    assert res["total"] == 2
    assert names(res) == ["St. Example Academy", "St. Sample High School"]


def test_catholic_high_schools(conn):
    res = db.run_search(conn, SchoolQuery(religious_groups=["catholic"], levels=["secondary"]))
    assert names(res) == ["St. Sample High School"]


def test_affiliation_city_and_size(conn):
    assert names(db.run_search(conn, SchoolQuery(affiliation="jewish"))) == \
        ["Example Hebrew Day School"]
    assert len(db.run_search(conn, SchoolQuery(cities=["san jose"]))["rows"]) == 2
    big = db.run_search(conn, SchoolQuery(min_enrollment=500, sort="enrollment_desc"))
    assert names(big) == ["St. Sample High School", "St. Example Academy"]


def test_radius_and_place_fallback(conn):
    near = db.run_search(conn, SchoolQuery(place="San Jose", radius_miles=10, sort="distance"))
    assert near["rows"][0]["miles"] is not None
    assert near["rows"] == sorted(near["rows"], key=lambda r: r["miles"])
    # Campbell is not in PLACES: center comes from loaded schools in that city
    assert db.resolve_place(conn, "Campbell") == pytest.approx((37.29, -121.95))
    assert "error" in db.run_search(conn, SchoolQuery(place="Atlantis"))


def test_unverified_tuition_is_ignored(conn):
    db.add_fact(conn, "X0000001", "tuition_max", {"amount": 38500}, "https://example-prep.test/t",
                "Tuition is $38,500", True, "stub")
    db.add_fact(conn, "X0000002", "tuition_max", {"amount": 99}, "https://x.test", "made up",
                False, "stub")
    cheap = db.run_search(conn, SchoolQuery(max_tuition=40000))
    assert names(cheap) == ["Example Valley Preparatory"]
    detail = db.get_school(conn, "X0000001")
    assert detail["facts"][0]["quote"] == "Tuition is $38,500"


def test_stats_and_tools(conn):
    stats = db.run_stats(conn, SchoolQuery(), "religious_group")
    assert {r["value"]: r["schools"] for r in stats["rows"]} == \
        {"catholic": 2, "other_religious": 1, "nonsectarian": 1}
    out = json.loads(run_tool(conn, "search_schools",
                              {"religious_groups": ["catholic"], "levels": ["combined"]}))
    assert [r["ppin"] for r in out["rows"]] == ["X0000002"] and out["total"] == 1
    out = json.loads(run_tool(conn, "count_schools", {"group_by": "city"}))
    assert {r["value"] for r in out["rows"]} == {"San Jose", "Santa Clara", "Campbell"}
    bad = json.loads(run_tool(conn, "search_schools", {"levels": ["college"]}))
    assert "error" in bad


def test_semantic_search(conn):
    a, b = np.zeros(384, dtype=np.float32), np.zeros(384, dtype=np.float32)
    a[0], b[1] = 1, 1
    db.replace_chunks(conn, "X0000001", "https://example-prep.test/robotics",
                      ["Our robotics team"], [a])
    db.replace_chunks(conn, "X0000002", "https://st-example.test/arts", ["Fine arts"], [b])
    hits = db.semantic_search(conn, a, limit=1)
    assert hits[0]["ppin"] == "X0000001"


def test_find_output(conn, capsys):
    from school_finder.cli import print_find
    from school_finder.translate import Translation

    print_find(conn, Translation("search", SchoolQuery(religious_groups=["catholic"], limit=1)))
    out = capsys.readouterr().out
    assert out.startswith("Showing catholic schools, sorted by name")
    assert "St. Example Academy" in out
    assert "2 schools matched (showing 1" in out

    print_find(conn, Translation("count", SchoolQuery(), "religious_group"))
    out = capsys.readouterr().out
    assert "Catholic" in out and "Total: 4 schools" in out
