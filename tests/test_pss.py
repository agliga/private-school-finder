from pathlib import Path

import pytest

from school_finder.pss import read_pss, resolve_columns

CSV = Path(__file__).parent / "fixtures" / "pss_sample.csv"


def test_reads_and_filters_by_state():
    schools = list(read_pss(CSV, state="CA", pss_year="2023-24"))
    assert [s.ppin for s in schools] == ["X0000001", "X0000002"]
    prep = schools[0]
    assert prep.name == "Example Valley Preparatory"
    assert prep.level == "secondary"
    assert prep.religious_group == "nonsectarian"
    assert prep.enrollment == 412
    assert prep.lat == pytest.approx(37.35)


def test_catholic_defaults_affiliation():
    st = list(read_pss(CSV, state="CA"))[1]
    assert st.religious_group == "catholic"
    assert st.affiliation == "Roman Catholic"


def test_missing_codes_become_none():
    nv = list(read_pss(CSV, state="NV"))[0]
    assert nv.lat is None and nv.lon is None


def test_year_suffixed_columns_resolve():
    cols = resolve_columns(["PPIN", "PINST", "LATITUDE24"])
    assert cols["lat"] == "LATITUDE24"


def test_required_columns():
    with pytest.raises(ValueError):
        resolve_columns(["PINST"])
