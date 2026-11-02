from school_finder.agent import parse_ppins
from school_finder.evals import (
    college_recall,
    regressions,
    score_extraction,
    set_metrics,
    tuition_match,
)
from school_finder.models import SchoolFacts
from school_finder.scoring import college_outcome_score, normalize_college, tuition_band

SELECTIVE = frozenset({normalize_college("Stanford University"), normalize_college("UCLA")})


def test_tuition_bands():
    assert tuition_band(None) == "not published"
    assert tuition_band(12_000) == "under $15k"
    assert tuition_band(38_500) == "$30k-$45k"
    assert tuition_band(60_000) == "$45k+"


def test_outcome_score():
    assert college_outcome_score([], SELECTIVE) is None
    score = college_outcome_score(["Stanford University", "UC Davis", "UCLA", "UCLA"], SELECTIVE)
    assert score == round(2 / 3, 3)  # duplicates collapse


def test_selective_list_loads():
    from school_finder.scoring import selective_colleges

    assert normalize_college("Stanford University") in selective_colleges()


def test_tuition_match_tolerance_and_nulls():
    assert tuition_match(38_600, 38_500)
    assert not tuition_match(42_000, 38_500)
    assert tuition_match(None, None)
    assert not tuition_match(30_000, None)


def test_college_recall_normalizes():
    assert college_recall(["Stanford University", "U.C. Davis"], ["stanford university"]) == 1.0
    assert college_recall([], []) is None


def test_score_extraction_flags_hallucination():
    label = {"ppin": "X1", "tuition_max": None, "has_matriculation": False}
    facts = SchoolFacts.model_validate({
        "tuition": {"amount_max": 20000, "source_url": "u", "quote": "q"},
        "matriculation": {"colleges": ["UCLA"], "source_url": "u", "quote": "q"},
    })
    item = score_extraction(label, facts, {"tuition": False, "matriculation": False})
    assert item.hallucinations == 2
    assert not item.tuition_ok
    assert item.verified_fields == 0


def test_set_metrics():
    m = set_metrics(["a", "b", "z"], must_include=["a", "c"], must_exclude=["z"])
    assert m == {"recall": 0.5, "exclusion_violations": 1}


def test_regression_gate():
    base = {"extraction": {"tuition_accuracy": 0.9, "hallucination_rate": 0.05}}
    ok = {"extraction": {"tuition_accuracy": 0.88, "hallucination_rate": 0.06}}
    bad = {"extraction": {"tuition_accuracy": 0.7, "hallucination_rate": 0.2}}
    assert regressions(ok, base) == []
    assert len(regressions(bad, base)) == 2


def test_parse_ppins():
    text = 'Here are my picks.\n{"ppins": ["X0000002", "X0000001"]}'
    assert parse_ppins(text) == ["X0000002", "X0000001"]
    assert parse_ppins("no json") == []
