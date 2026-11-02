"""Eval harness.

Two suites, both reproducible:

1. Extraction: runs the extractor on *frozen page snapshots* (evals/snapshots/<ppin>.json)
   and compares with hand labels (evals/labels/extraction.jsonl). Frozen pages mean a
   score change comes from a prompt/model/code change, not from a school editing its site.
2. Queries: runs the agent on evals/queries.jsonl and checks the schools it returns.

Each run writes evals/results/<run_id>.json with the git SHA, models and per-item results,
and `--check` fails if a headline metric drops more than the allowed margin vs
evals/baseline.json. This is the CI gate.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

from .crawl import Page
from .extract import LLM, extract_facts
from .models import SchoolFacts
from .scoring import normalize_college

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "evals"
TUITION_TOLERANCE = 0.02  # 2%


# ---------- metric helpers (pure, unit-tested) ----------

def tuition_match(pred: float | None, label: float | None) -> bool:
    if label is None:
        return pred is None
    if pred is None:
        return False
    return abs(pred - label) <= max(TUITION_TOLERANCE * label, 250)


def hallucinated(pred, label) -> bool:
    """Model gave a value the school does not publish."""
    return label is None and pred is not None


def college_recall(pred: list[str], label_sample: list[str]) -> float | None:
    if not label_sample:
        return None
    got = {normalize_college(c) for c in pred}
    return sum(normalize_college(c) in got for c in label_sample) / len(label_sample)


def set_metrics(pred: list[str], must_include: list[str], must_exclude: list[str]) -> dict:
    p = set(pred)
    recall = (len(p & set(must_include)) / len(must_include)) if must_include else 1.0
    violations = len(p & set(must_exclude))
    return {"recall": recall, "exclusion_violations": violations}


# ---------- extraction suite ----------

@dataclass
class ExtractionItem:
    ppin: str
    tuition_ok: bool
    tuition_min_ok: bool
    hallucinations: int
    cited_fields: int
    verified_fields: int
    college_recall: float | None
    affiliation_ok: bool | None


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_snapshot(ppin: str) -> tuple[str, list[Page]]:
    data = json.loads((EVALS / "snapshots" / f"{ppin}.json").read_text())
    return data["name"], [Page(**p) for p in data["pages"]]


def score_extraction(label: dict, facts: SchoolFacts, verified: dict[str, bool]) -> ExtractionItem:
    t = facts.tuition
    pred_max = t.amount_max if t else None
    pred_min = t.amount_min if t else None
    pred_colleges = facts.matriculation.colleges if facts.matriculation else []
    halluc = int(hallucinated(pred_max, label.get("tuition_max"))) + int(
        not label.get("has_matriculation") and bool(pred_colleges)
    )
    aff_label = label.get("affiliation")
    aff_pred = facts.affiliation_name
    aff_ok = None
    if aff_label or aff_pred:
        aff_ok = bool(aff_label and aff_pred and aff_label.lower() in aff_pred.lower())
    return ExtractionItem(
        ppin=label["ppin"],
        tuition_ok=tuition_match(pred_max, label.get("tuition_max")),
        tuition_min_ok=tuition_match(pred_min, label.get("tuition_min", label.get("tuition_max"))),
        hallucinations=int(halluc),
        cited_fields=len(verified),
        verified_fields=sum(verified.values()),
        college_recall=college_recall(pred_colleges, label.get("colleges_sample", [])),
        affiliation_ok=aff_ok,
    )


def run_extraction(llm: LLM, labels: list[dict]) -> tuple[dict, list[dict]]:
    items: list[ExtractionItem] = []
    for label in labels:
        name, pages = load_snapshot(label["ppin"])
        facts, verified = extract_facts(llm, name, pages)
        items.append(score_extraction(label, facts, verified))
    if not items:
        return {}, []
    cited = sum(i.cited_fields for i in items)
    recalls = [i.college_recall for i in items if i.college_recall is not None]
    affs = [i.affiliation_ok for i in items if i.affiliation_ok is not None]
    summary = {
        "n": len(items),
        "tuition_accuracy": mean(i.tuition_ok for i in items),
        "tuition_min_accuracy": mean(i.tuition_min_ok for i in items),
        "hallucination_rate": sum(i.hallucinations for i in items) / len(items),
        "citation_verified_rate": (sum(i.verified_fields for i in items) / cited) if cited else 1.0,
        "college_recall": mean(recalls) if recalls else None,
        "affiliation_accuracy": mean(affs) if affs else None,
    }
    return summary, [asdict(i) for i in items]


# ---------- query suite ----------

def run_queries(conn, queries: list[dict]) -> tuple[dict, list[dict]]:
    from .agent import ask

    rows = []
    for q in queries:
        t0 = time.time()
        res = ask(conn, q["question"])
        m = set_metrics(res.ppins, q.get("must_include", []), q.get("must_exclude", []))
        rows.append({"question": q["question"], **m, "returned": res.ppins,
                     "tool_calls": len(res.tool_calls), "seconds": round(time.time() - t0, 1)})
    if not rows:
        return {}, []
    return {
        "n": len(rows),
        "query_recall": mean(r["recall"] for r in rows),
        "exclusion_violation_rate": mean(r["exclusion_violations"] > 0 for r in rows),
        "avg_tool_calls": mean(r["tool_calls"] for r in rows),
    }, rows


# ---------- run bookkeeping + regression gate ----------

HIGHER_IS_BETTER = {"tuition_accuracy", "tuition_min_accuracy", "citation_verified_rate",
                    "college_recall", "affiliation_accuracy", "query_recall"}
LOWER_IS_BETTER = {"hallucination_rate", "exclusion_violation_rate"}


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       text=True).strip()
    except Exception:
        return "unknown"


def regressions(current: dict, baseline: dict, margin: float = 0.05) -> list[str]:
    problems = []
    for suite, metrics in baseline.items():
        for key, base in metrics.items():
            cur = current.get(suite, {}).get(key)
            if cur is None or base is None:
                continue
            if key in HIGHER_IS_BETTER and cur < base - margin:
                problems.append(f"{suite}.{key}: {cur:.3f} < baseline {base:.3f}")
            if key in LOWER_IS_BETTER and cur > base + margin:
                problems.append(f"{suite}.{key}: {cur:.3f} > baseline {base:.3f}")
    return problems


def write_run(summary: dict, details: dict, meta: dict) -> Path:
    out = EVALS / "results"
    out.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    path = out / f"{run_id}.json"
    path.write_text(json.dumps({"run_id": run_id, "git_sha": git_sha(), **meta,
                                "summary": summary, "details": details}, indent=2))
    return path
