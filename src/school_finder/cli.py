"""Command line: load-pss | enrich | snapshot | ask | eval | mcp"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import settings


def cmd_load_pss(a):
    from . import db
    from .pss import read_pss

    schools = list(read_pss(Path(a.csv), state=a.state, pss_year=a.year))
    if a.county_zip_prefix:
        schools = [s for s in schools if (s.zip or "").startswith(tuple(a.county_zip_prefix))]
    with db.connect() as conn:
        n = db.upsert_schools(conn, schools)
        conn.commit()
    print(f"Loaded {n} schools")


def _schools(conn, a) -> list[dict]:
    if a.ppin:
        return list(conn.execute("SELECT * FROM schools WHERE ppin = ANY(%s)", (a.ppin,)))
    sql = "SELECT * FROM schools WHERE (%s::text IS NULL OR city ILIKE %s) ORDER BY ppin LIMIT %s"
    return list(conn.execute(sql, (a.city, a.city, a.limit)))


def cmd_enrich(a):
    from . import db
    from .crawl import Crawler
    from .enrich import enrich_school
    from .extract import AnthropicLLM

    llm = AnthropicLLM(settings.extract_model)
    crawler = Crawler()
    with db.connect() as conn:
        for school in _schools(conn, a):
            print(json.dumps(enrich_school(conn, school, crawler, llm, embed_pages=not a.no_embed)))


def cmd_snapshot(a):
    """Freeze a school's pages for the extraction eval."""
    from dataclasses import asdict

    from . import db
    from .crawl import Crawler
    from .enrich import find_website

    out = Path("evals/snapshots")
    out.mkdir(parents=True, exist_ok=True)
    crawler = Crawler()
    with db.connect() as conn:
        for school in _schools(conn, a):
            site = school.get("website") or find_website(school)
            pages = crawler.crawl_school(site) if site else []
            (out / f"{school['ppin']}.json").write_text(json.dumps(
                {"ppin": school["ppin"], "name": school["name"], "website": site,
                 "pages": [{k: v for k, v in asdict(p).items()} for p in pages]}, indent=2))
            print(f"{school['ppin']}: {len(pages)} pages")


def cmd_ask(a):
    from . import db
    from .agent import ask

    with db.connect() as conn:
        res = ask(conn, a.question)
    print(res.answer)
    if a.verbose:
        print(json.dumps(res.tool_calls, indent=2), file=sys.stderr)


def cmd_eval(a):
    from . import evals

    summary, details = {}, {}
    if a.suite in ("extraction", "all"):
        from .extract import AnthropicLLM

        labels = evals.load_jsonl(evals.EVALS / "labels" / "extraction.jsonl")
        summary["extraction"], details["extraction"] = evals.run_extraction(
            AnthropicLLM(settings.extract_model), labels)
    if a.suite in ("queries", "all"):
        from . import db

        with db.connect() as conn:
            summary["queries"], details["queries"] = evals.run_queries(
                conn, evals.load_jsonl(evals.EVALS / "queries.jsonl"))
    path = evals.write_run(summary, details, {"extract_model": settings.extract_model,
                                              "agent_model": settings.agent_model})
    print(json.dumps(summary, indent=2))
    print(f"Wrote {path}")
    if a.update_baseline:
        (evals.EVALS / "baseline.json").write_text(json.dumps(summary, indent=2) + "\n")
        print("Baseline updated")
    if a.check:
        base_path = evals.EVALS / "baseline.json"
        baseline = json.loads(base_path.read_text()) if base_path.exists() else {}
        problems = evals.regressions(summary, baseline)
        if problems:
            print("REGRESSIONS:\n  " + "\n  ".join(problems))
            sys.exit(1)
        print("No regressions vs baseline")


def cmd_mcp(_a):
    from .mcp_server import main

    main()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="school-finder")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("load-pss", help="Load the NCES PSS CSV into Postgres")
    s.add_argument("csv")
    s.add_argument("--state", default="CA")
    s.add_argument("--year", help="PSS release, e.g. 2023-24")
    s.add_argument("--county-zip-prefix", nargs="*", help="e.g. 950 951 to keep San Jose area")
    s.set_defaults(fn=cmd_load_pss)

    for name, fn, help_ in (("enrich", cmd_enrich, "Find site, crawl, extract, embed"),
                            ("snapshot", cmd_snapshot, "Freeze pages for evals")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--ppin", nargs="*")
        s.add_argument("--city")
        s.add_argument("--limit", type=int, default=10)
        if name == "enrich":
            s.add_argument("--no-embed", action="store_true")
        s.set_defaults(fn=fn)

    s = sub.add_parser("ask", help="Ask the agent a question")
    s.add_argument("question")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("eval", help="Run evals")
    s.add_argument("--suite", choices=["extraction", "queries", "all"], default="extraction")
    s.add_argument("--check", action="store_true", help="Fail on regression vs baseline")
    s.add_argument("--update-baseline", action="store_true")
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("mcp", help="Run the MCP server (stdio)")
    s.set_defaults(fn=cmd_mcp)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
