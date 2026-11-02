from pathlib import Path

import pytest

from school_finder.pss import read_pss, resolve_columns

CSV = Path(__file__).parent / "fixtures" / "pss_sample.csv"


def by_ppin(state="CA"):
    return {s.ppin: s for s in read_pss(CSV, state=state, pss_year="2021-22")}


def test_reads_and_filters_by_state():
    schools = by_ppin()
    assert set(schools) == {"X0000001", "X0000002", "X0000004", "X0000005"}
    prep = schools["X0000001"]
    assert prep.name == "Example Valley Preparatory"
    assert prep.city == "San Jose"
    assert prep.religious_group == "nonsectarian"
    assert prep.affiliation is None          # ORIENT 30 = nonsectarian
    assert prep.typology == "nonsectarian_regular"
    assert prep.enrollment == 412
    assert prep.lat == pytest.approx(37.35)


def test_prefers_newest_level_column():
    # LEVEL is 9 (junk) in the fixture; LEVEL4 holds the real value
    schools = by_ppin()
    assert schools["X0000001"].level == "secondary"
    assert schools["X0000002"].level == "combined"
    assert schools["X0000004"].level == "elementary"


def test_affiliation_and_typology_codes():
    schools = by_ppin()
    assert schools["X0000002"].affiliation == "Roman Catholic"
    assert schools["X0000002"].typology == "catholic_diocesan"
    assert schools["X0000004"].affiliation == "Jewish"
    assert schools["X0000005"].affiliation == "Roman Catholic"   # zero-padded "01"
    assert schools["X0000005"].typology == "catholic_private"


def test_missing_codes_become_none():
    nv = by_ppin("NV")["X0000003"]
    assert nv.lat is None and nv.lon is None
    assert nv.affiliation == "Baptist"


def test_year_suffixed_columns_resolve():
    cols = resolve_columns(["PPIN", "PINST", "LATITUDE22", "LEVEL", "LEVEL4"])
    assert cols["lat"] == "LATITUDE22"
    assert cols["level"] == "LEVEL4"


def test_required_columns():
    with pytest.raises(ValueError):
        resolve_columns(["PINST"])
