from decimal import Decimal

from school_finder.render import schools_table, stats_table, to_csv

ROWS = [
    {"name": "St. Example Academy", "city": "Santa Clara", "level": "combined",
     "religious_group": "catholic", "affiliation": "Roman Catholic", "enrollment": 650,
     "miles": None, "tuition_max": None, "college_outcome_score": None},
    {"name": "Example Valley Preparatory", "city": "San Jose", "level": "secondary",
     "religious_group": "nonsectarian", "affiliation": None, "enrollment": 412,
     "miles": None, "tuition_max": Decimal("38500"), "college_outcome_score": None},
]


def test_schools_table_hides_empty_columns():
    out = schools_table(ROWS)
    lines = out.splitlines()
    assert lines[0].split() == ["#", "School", "City", "Level", "Affiliation", "Students", "Tuition"]
    assert "Miles" not in out and "Outcome" not in out
    assert "Nonsectarian" in out and "$38,500" in out and "K-12/Combined" in out


def test_stats_table():
    out = stats_table([{"value": "catholic", "schools": 3, "students": 2000},
                       {"value": "nonsectarian", "schools": 1, "students": None}],
                      "religious_group")
    assert "Catholic" in out and "2,000" in out and out.endswith("Total: 4 schools")


def test_csv():
    assert to_csv(ROWS).splitlines()[0].startswith("name,city,level")
    assert to_csv([]) == ""
