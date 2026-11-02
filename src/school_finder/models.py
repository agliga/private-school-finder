"""Typed records shared by the pipeline, the agent and the evals."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReligiousGroup = Literal["catholic", "other_religious", "nonsectarian"]
Level = Literal["elementary", "secondary", "combined"]


class School(BaseModel):
    ppin: str
    name: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    lat: float | None = None
    lon: float | None = None
    religious_group: ReligiousGroup | None = None
    affiliation: str | None = None
    level: Level | None = None
    typology: str | None = None
    enrollment: int | None = None
    website: str | None = None
    pss_year: str | None = None


class Cited(BaseModel):
    """A value plus the evidence for it. No quote, no fact."""

    source_url: str
    quote: str = Field(description="Verbatim text copied from the page that supports the value")


class Tuition(Cited):
    amount_min: float | None = Field(None, description="Lowest annual tuition in USD")
    amount_max: float | None = Field(None, description="Highest annual tuition in USD")
    school_year: str | None = Field(None, description="e.g. 2026-27")
    grade_note: str | None = Field(None, description="Which grades the amounts apply to")


class Matriculation(Cited):
    colleges: list[str] = Field(description="College names graduates enrolled in or were admitted to")
    kind: Literal["enrolled", "admitted", "unknown"] = "unknown"
    class_years: str | None = Field(None, description="e.g. 'Class of 2022-2025'")


class Schedule(Cited):
    start_time: str | None = Field(None, description="Regular school-day start, 24h 'HH:MM'")
    end_time: str | None = Field(None, description="Regular school-day dismissal, 24h 'HH:MM'")
    applies_to: str | None = Field(
        None, description="Which grades/days these times are for, e.g. 'grades 9-12, Mon-Thu'")


class SchoolCalendar(Cited):
    school_year: str = Field(description="e.g. '2026-27'")
    first_day: str | None = Field(None, description="First day of school for students, YYYY-MM-DD")
    last_day: str | None = Field(None, description="Last day of school for students, YYYY-MM-DD")


class SchoolFacts(BaseModel):
    """What the enrichment agent returns for one school.

    Fields are None when the site does not publish them. The agent must never guess.
    """

    tuition: Tuition | None = None
    matriculation: Matriculation | None = None
    affiliation: Cited | None = None
    affiliation_name: str | None = None
    schedule: Schedule | None = None
    calendar: SchoolCalendar | None = None
    notes: str | None = None
