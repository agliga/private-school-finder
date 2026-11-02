import pytest
from pydantic import ValidationError

from school_finder.query import SchoolQuery, build_search_sql, build_stats_sql


def test_catholic_high_schools_sql():
    q = SchoolQuery(religious_groups=["catholic"], levels=["secondary"], limit=500)
    sql, params = build_search_sql(q)
    assert "religious_group = ANY(%(groups)s)" in sql
    assert "level = ANY(%(levels)s)" in sql
    assert "earth_distance" not in sql          # no location -> no radius filter
    assert params == {"groups": ["catholic"], "levels": ["secondary"], "limit": 500}


def test_empty_query_lists_everything():
    q = SchoolQuery()
    sql, params = build_search_sql(q)
    assert "WHERE" not in sql
    assert q.is_empty()


def test_radius_search_uses_center_and_default_radius():
    q = SchoolQuery(place="San Jose", sort="distance")
    sql, params = build_search_sql(q, (37.3, -121.9))
    assert "earth_box" in sql and "ORDER BY miles" in sql
    assert params["radius"] == pytest.approx(10 * 1609.344)


def test_distance_sort_without_center_falls_back_to_name():
    sql, _ = build_search_sql(SchoolQuery(sort="distance"))
    assert "ORDER BY name" in sql


def test_cities_are_case_insensitive():
    _, params = build_search_sql(SchoolQuery(cities=["San Jose ", "CAMPBELL"]))
    assert params["cities"] == ["san jose", "campbell"]


def test_user_text_is_parameterized_not_interpolated():
    sql, params = build_search_sql(SchoolQuery(name_contains="x'; drop table schools;--"))
    assert "drop table" not in sql
    assert params["name"] == "%x'; drop table schools;--%"


def test_stats_sql_groups():
    sql, params = build_stats_sql(SchoolQuery(religious_groups=["catholic"]), "city")
    assert "GROUP BY 1" in sql and "coalesce(city" in sql
    with pytest.raises(ValueError):
        build_stats_sql(SchoolQuery(), "name; drop table")  # type: ignore[arg-type]


def test_validation_rejects_bad_values():
    with pytest.raises(ValidationError):
        SchoolQuery(levels=["college"])
    with pytest.raises(ValidationError):
        SchoolQuery(limit=10_000)


def test_describe():
    q = SchoolQuery(religious_groups=["catholic"], levels=["secondary"], cities=["San Jose"])
    assert q.describe() == "catholic high schools in San Jose, sorted by name"
    q = SchoolQuery(affiliation="Jewish", place="Palo Alto", radius_miles=5, sort="distance")
    assert q.describe() == "Jewish schools within 5.0 mi of Palo Alto, sorted by distance"
