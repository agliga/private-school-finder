import json
from pathlib import Path

from school_finder.evals import compare_translation, run_translate
from school_finder.tools import COUNT_TOOL, SEARCH_TOOL
from school_finder.translate import translate


class StubToolLLM:
    def __init__(self, answers: dict[str, tuple[str, dict]]):
        self.answers = answers

    def choose_tool(self, system, user, tools):
        assert {t["name"] for t in tools} == {"search_schools", "count_schools"}
        return self.answers[user]


def test_translate_search():
    llm = StubToolLLM({"all catholic high schools": (
        "search_schools", {"religious_groups": ["catholic"], "levels": ["secondary"], "limit": 500})})
    t = translate(llm, "all catholic high schools")
    assert t.kind == "search"
    assert t.query.religious_groups == ["catholic"] and t.query.limit == 500


def test_translate_count():
    llm = StubToolLLM({"how many by city": ("count_schools", {"group_by": "city"})})
    t = translate(llm, "how many by city")
    assert t.kind == "count" and t.group_by == "city" and t.query.is_empty()


def test_compare_translation_rules():
    exp = {"religious_groups": ["catholic"], "levels": ["secondary"]}
    ok = {"religious_groups": ["catholic"], "levels": ["secondary"], "limit": 50, "sort": "name"}
    assert compare_translation(exp, "search", ok, None) == []
    invented = {**ok, "cities": ["San Jose"]}
    assert compare_translation(exp, "search", invented, None) == [
        "cities: expected None, got ['San Jose']"]
    # list order and case don't matter
    assert compare_translation({"cities": ["San Jose"]}, "search", {"cities": ["san jose"]},
                               None) == []
    # default radius is accepted for "near X"
    assert compare_translation({"place": "Palo Alto"}, "search",
                               {"place": "Palo Alto", "radius_miles": 10}, None) == []
    assert compare_translation({"kind": "count", "group_by": "city"}, "search", {}, None)


def test_eval_file_is_valid_and_runs_with_perfect_stub():
    path = Path(__file__).resolve().parents[1] / "evals" / "translate.jsonl"
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(items) >= 20
    answers = {}
    for it in items:
        exp = dict(it["expected"])
        kind = exp.pop("kind", "search")
        name = "count_schools" if kind == "count" else "search_schools"
        answers[it["question"]] = (name, exp)
    summary, rows = run_translate(StubToolLLM(answers), items)
    assert summary["translate_accuracy"] == 1.0, [r for r in rows if not r["ok"]]


def test_tool_schemas():
    assert SEARCH_TOOL["input_schema"]["type"] == "object"
    assert "religious_groups" in SEARCH_TOOL["input_schema"]["properties"]
    assert COUNT_TOOL["input_schema"]["required"] == ["group_by"]
