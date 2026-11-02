"""Structured school queries.

`SchoolQuery` is the single source of truth for filters. It is:
- the JSON schema Claude fills in when translating a plain-English ask,
- turned into parameterized SQL here (pure functions, unit-tested without a database),
- what the translation eval compares against expected answers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import Level, ReligiousGroup

Typology = Literal[
    "catholic_parochial", "catholic_diocesan", "catholic_private", "conservative_christian",
    "religious_affiliated", "religious_unaffiliated", "nonsectarian_regular",
    "nonsectarian_special_emphasis", "nonsectarian_special_education",
]
Sort = Literal["name", "distance", "drive_time", "enrollment_desc", "enrollment_asc",
               "tuition_asc", "outcome_desc"]
GroupBy = Literal["religious_group", "affiliation", "city", "level", "typology"]

METERS_PER_MILE = 1609.344
DEFAULT_RADIUS_MILES = 10


class SchoolQuery(BaseModel):
    """Filters for finding private schools. Leave a field null unless the user asked for it."""

    place: str | None = Field(
        None, description="Center for a radius search when the user says 'near X' or "
        "'within N miles of X' (a city name). Use `cities` instead for 'in X'.")
    radius_miles: float | None = Field(
        None, description=f"Radius for `place`; default {DEFAULT_RADIUS_MILES} if 'near' with no distance.")
    cities: list[str] | None = Field(
        None, description="Only schools whose city is one of these ('schools in Campbell').")
    name_contains: str | None = Field(None, description="Text the school name must contain.")
    religious_groups: list[ReligiousGroup] | None = Field(
        None, description="catholic | other_religious | nonsectarian. 'Religious' = catholic + "
        "other_religious. 'Secular' or 'non-religious' = nonsectarian.")
    affiliation: str | None = Field(
        None, description="Specific denomination, e.g. 'Jewish', 'Lutheran', 'Baptist', "
        "'Islamic', 'Episcopal'. For Catholic use religious_groups=['catholic'] instead.")
    typologies: list[Typology] | None = Field(
        None, description="NCES school type. Use for 'special education schools' "
        "(nonsectarian_special_education), 'special program emphasis' such as arts or "
        "alternative schools (nonsectarian_special_emphasis), 'conservative Christian', or a "
        "kind of Catholic school. For Montessori/Waldorf use name_contains.")
    levels: list[Level] | None = Field(
        None, description="'high school' = ['secondary']; 'elementary' or 'middle school' = "
        "['elementary']; 'K-12' = ['combined']. Add 'combined' only if the user wants schools "
        "that also include those grades.")
    min_enrollment: int | None = Field(None, description="'large schools' etc. Only if asked.")
    max_enrollment: int | None = Field(None, description="'small schools' etc. Only if asked.")
    max_tuition: float | None = Field(
        None, description="Annual tuition cap in USD. Only schools with published tuition match.")
    min_outcome_score: float | None = Field(
        None, description="0-1 share of a school's college list that is selective.")
    origin: str | None = Field(
        None, description="Starting point for distance and drive times: a street address, "
        "'current location' (for 'from here', 'from my location'), or 'home'. Set only when the "
        "user asks about distance, drive/commute time or 'from' somewhere. Adds miles, morning "
        "and afternoon drive times (with traffic), start/end times and first/last day.")
    max_drive_minutes: int | None = Field(
        None, description="'within a 20 minute drive' -> 20. Needs origin.")
    sort: Sort = Field("name", description="'distance' needs place or origin; 'drive_time' "
                       "(morning drive) needs origin.")
    limit: int = Field(50, ge=1, le=500, description="Max rows. 'all' = 500.")

    def is_empty(self) -> bool:
        return not any(v for k, v in self.model_dump().items() if k not in {"sort", "limit"})

    def describe(self) -> str:
        """Human-readable summary of the filters, shown before results."""
        parts = []
        if self.religious_groups:
            parts.append(" or ".join(g.replace("_", " ") for g in self.religious_groups))
        if self.affiliation:
            parts.append(self.affiliation)
        if self.typologies:
            parts.append(" or ".join(t.replace("_", " ") for t in self.typologies))
        if self.levels:
            parts.append(" or ".join({"secondary": "high", "elementary": "elementary/middle",
                                      "combined": "combined (K-12)"}[lv] for lv in self.levels))
        parts.append("schools")
        if self.cities:
            parts.append("in " + ", ".join(self.cities))
        if self.place:
            parts.append(f"within {self.radius_miles or DEFAULT_RADIUS_MILES} mi of {self.place}")
        if self.name_contains:
            parts.append(f'named like "{self.name_contains}"')
        if self.min_enrollment:
            parts.append(f"with {self.min_enrollment}+ students")
        if self.max_enrollment:
            parts.append(f"with at most {self.max_enrollment} students")
        if self.max_tuition:
            parts.append(f"tuition up to ${self.max_tuition:,.0f}")
        if self.min_outcome_score is not None:
            parts.append(f"college outcome score >= {self.min_outcome_score}")
        if self.max_drive_minutes:
            parts.append(f"within a {self.max_drive_minutes}-minute drive")
        if self.origin:
            parts.append(f"from {self.origin}")
        return " ".join(parts) + f", sorted by {self.sort.replace('_', ' ')}"


def _where(q: SchoolQuery, center: tuple[float, float] | None, filter_radius: bool = True,
           radius_miles: float | None = None) -> tuple[list[str], dict[str, Any]]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if center:
        params.update(lat=center[0], lon=center[1])
    if center and filter_radius:
        params["radius"] = (radius_miles or q.radius_miles or DEFAULT_RADIUS_MILES) * METERS_PER_MILE
        where += ["earth_box(ll_to_earth(%(lat)s, %(lon)s), %(radius)s) @> ll_to_earth(lat, lon)",
                  "earth_distance(ll_to_earth(%(lat)s, %(lon)s), ll_to_earth(lat, lon)) <= %(radius)s"]
    if q.cities:
        where.append("lower(city) = ANY(%(cities)s)")
        params["cities"] = [c.strip().lower() for c in q.cities]
    if q.name_contains:
        where.append("name ILIKE %(name)s")
        params["name"] = f"%{q.name_contains}%"
    if q.religious_groups:
        where.append("religious_group = ANY(%(groups)s)")
        params["groups"] = list(q.religious_groups)
    if q.affiliation:
        where.append("affiliation ILIKE %(affiliation)s")
        params["affiliation"] = f"%{q.affiliation}%"
    if q.typologies:
        where.append("typology = ANY(%(typologies)s)")
        params["typologies"] = list(q.typologies)
    if q.levels:
        where.append("level = ANY(%(levels)s)")
        params["levels"] = list(q.levels)
    if q.min_enrollment is not None:
        where.append("enrollment >= %(min_enroll)s")
        params["min_enroll"] = q.min_enrollment
    if q.max_enrollment is not None:
        where.append("enrollment <= %(max_enroll)s")
        params["max_enroll"] = q.max_enrollment
    if q.max_tuition is not None:
        where.append("tuition_max <= %(max_tuition)s")
        params["max_tuition"] = q.max_tuition
    if q.min_outcome_score is not None:
        where.append("college_outcome_score >= %(min_score)s")
        params["min_score"] = q.min_outcome_score
    return where, params


ORDER_BY = {
    "name": "name",
    "distance": "miles NULLS LAST, name",
    "drive_time": "miles NULLS LAST, name",   # pre-sort by distance; re-sorted after routing
    "enrollment_desc": "enrollment DESC NULLS LAST, name",
    "enrollment_asc": "enrollment ASC NULLS LAST, name",
    "tuition_asc": "tuition_max ASC NULLS LAST, name",
    "outcome_desc": "college_outcome_score DESC NULLS LAST, name",
}


def build_search_sql(q: SchoolQuery, center: tuple[float, float] | None = None,
                     filter_radius: bool = True, radius_miles: float | None = None
                     ) -> tuple[str, dict[str, Any]]:
    """`center` gives distances (and a radius filter when `filter_radius`)."""
    where, params = _where(q, center, filter_radius, radius_miles)
    miles = (f"round((earth_distance(ll_to_earth(%(lat)s, %(lon)s), ll_to_earth(lat, lon))"
             f" / {METERS_PER_MILE})::numeric, 1)") if center else "NULL::numeric"
    sort = q.sort if (q.sort not in ("distance", "drive_time") or center) else "name"
    params["limit"] = q.limit
    sql = f"""
        SELECT ppin, name, address, city, zip, lat, lon, religious_group, affiliation, typology,
               level, enrollment, website, tuition_max, college_outcome_score, start_time,
               end_time, first_day, last_day, {miles} AS miles,
               count(*) OVER () AS total
        FROM school_summary
        {'WHERE ' + ' AND '.join(where) if where else ''}
        ORDER BY {ORDER_BY[sort]}
        LIMIT %(limit)s"""
    return sql, params


def build_stats_sql(q: SchoolQuery, group_by: GroupBy, center: tuple[float, float] | None = None
                    ) -> tuple[str, dict[str, Any]]:
    if group_by not in GroupBy.__args__:  # type: ignore[attr-defined]
        raise ValueError(f"bad group_by {group_by}")
    where, params = _where(q, center)
    sql = f"""
        SELECT coalesce({group_by}, 'unknown') AS value, count(*) AS schools,
               sum(enrollment) AS students
        FROM school_summary
        {'WHERE ' + ' AND '.join(where) if where else ''}
        GROUP BY 1 ORDER BY 2 DESC, 1"""
    return sql, params
