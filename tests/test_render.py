from decimal import Decimal

from school_finder.render import schools_table, stats_table, to_csv

ROWS = [
    {"name": "St. Example Academy", "address": "200 Sample Ave", "city": "Santa Clara", "level": "combined",
     "religious_group": "catholic", "affiliation": "Roman Catholic", "enrollment": 650,
     "miles": None, "tuition_max": None, "college_outcome_score": None},
    {"name": "Example Valley Preparatory", "city": "San Jose", "level": "secondary",
     "religious_group": "nonsectarian", "affiliation": None, "enrollment": 412,
     "miles": None, "tuition_max": Decimal("38500"), "college_outcome_score": None},
]


def test_schools_table_hides_empty_columns():
    out = schools_table(ROWS)
    lines = out.splitlines()
    assert lines[0].split() == ["#", "School", "Address", "City", "Level", "Affiliation", "Students",
                                "Tuition"]
    assert "Miles" not in out and "Outcome" not in out
    assert "Nonsectarian" in out and "$38,500" in out and "K-12/Combined" in out


def test_stats_table():
    out = stats_table([{"value": "catholic", "schools": 3, "students": 2000},
                       {"value": "nonsectarian", "schools": 1, "students": None}],
                      "religious_group")
    assert "Catholic" in out and "2,000" in out and out.endswith("Total: 4 schools")


def test_csv():
    assert to_csv(ROWS).splitlines()[0].startswith("name,address,city,level")
    assert to_csv([]) == ""


def test_travel_columns_and_footnotes():
    rows = [
        {"name": "A", "address": "1 A St", "city": "San Jose", "level": "secondary",
         "religious_group": "catholic", "enrollment": 500, "miles": 3.4, "drive_miles": 4.1,
         "am_minutes": 14, "am_depart": "07:20", "pm_minutes": 19, "pm_depart": "15:10",
         "start_time": "07:50", "end_time": "15:10", "first_day": "2026-08-19",
         "last_day": "2027-06-04"},
        {"name": "B", "address": "2 B St", "city": "Campbell", "level": "elementary",
         "religious_group": "nonsectarian", "enrollment": 90, "miles": 6.0,
         "am_depart": "07:30", "start_time_used": "08:00", "start_assumed": True,
         "end_time_used": "15:00", "end_assumed": True},
    ]
    out = schools_table(rows)
    header = out.splitlines()[0]
    for col in ("Address", "Miles", "AM drive (leave)", "Start", "PM drive (leave)", "End",
                "First day", "Last day"):
        assert col in header
    assert "14 min (7:20a)" in out and "7:50a" in out and "3:10p" in out
    assert "Aug 19" in out and "Jun 4" in out
    assert "~6.0" in out and "8:00a*" in out
    assert "straight-line" in out and "default used" in out
