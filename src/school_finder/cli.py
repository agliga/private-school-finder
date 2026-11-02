"""Command line: init-db | load-pss | enrich | snapshot | find | ask | chat | eval | mcp"""

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


def cmd_init_db(_a):
    from . import db

    with db.connect() as conn:
        db.apply_schema(conn)
    print("Schema applied")


def print_find(conn, t, as_json: bool = False, csv_path: str | None = None) -> None:
    from . import db, render

    if t.kind == "count":
        res = db.run_stats(conn, t.query, t.group_by or "religious_group")
        if "error" in res:
            print(res["error"])
            return
        if as_json:
            print(json.dumps(res, default=str, indent=2))
            return
        print(f"Counting {t.query.describe().removesuffix(', sorted by name')} by {t.group_by}\n")
        print(render.stats_table(res["rows"], t.group_by or "religious_group"))
        return

    res = db.run_search(conn, t.query)
    if "error" in res:
        print(res["error"])
        return
    rows = res["rows"]
    if as_json:
        print(json.dumps({"query": t.query.model_dump(exclude_none=True), **res}, default=str,
                         indent=2))
        return
    print(f"Showing {t.query.describe()}\n")
    if not rows:
        print("No schools matched.")
        return
    print(render.schools_table(rows))
    tr = res.get("travel")
    if tr:
        from datetime import date

        when = date.fromisoformat(tr["day"]).strftime("%a %b %-d")
        if tr.get("provider"):
            print(f"\nDrive times from {tr['origin']} with predicted traffic for {when}: morning "
                  "leaves before the start time, afternoon leaves school at the end time.")
            if tr["routed"] < len(rows):
                print(f"Drive times computed for the first {tr['routed']} schools "
                      "(MAX_ROUTE_SCHOOLS).")
        else:
            print(f"\nDistances from {tr['origin']}. {tr.get('note', '')}")
        if not tr.get("precise_origin", True):
            print("Location is approximate (from your IP). Set HOME_ADDRESS or install "
                  "CoreLocationCLI for exact times.")
    shown = len(rows)
    total = res["total"]
    more = f" (showing {shown}; add 'all' to see every one)" if total > shown else ""
    print(f"\n{total} school{'s' if total != 1 else ''} matched{more}")
    if csv_path:
        Path(csv_path).write_text(render.to_csv(rows))
        print(f"Saved {csv_path}")


def cmd_find(a):
    from . import db
    from .translate import AnthropicToolLLM, translate

    t = translate(AnthropicToolLLM(settings.translate_model), a.question)
    if a.verbose:
        print(json.dumps({"kind": t.kind, "group_by": t.group_by,
                          "filters": t.query.model_dump(exclude_none=True)}, indent=2),
              file=sys.stderr)
    with db.connect() as conn:
        print_find(conn, t, as_json=a.json, csv_path=a.csv)


def cmd_ask(a):
    from . import db
    from .agent import ask, strip_ppins_block

    with db.connect() as conn:
        res = ask(conn, a.question)
    print(strip_ppins_block(res.answer))
    if a.verbose:
        print(json.dumps(res.tool_calls, indent=2), file=sys.stderr)


def cmd_chat(a):
    from . import db
    from .agent import Conversation, strip_ppins_block

    print("Ask about private schools. Follow-ups refine the last answer. Ctrl-D or 'quit' to exit.")
    with db.connect() as conn:
        convo = Conversation(conn)
        while True:
            try:
                q = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if q.lower() in {"quit", "exit", "q"}:
                break
            if not q:
                continue
            res = convo.ask(q)
            print("\n" + strip_ppins_block(res.answer))
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
    if a.suite in ("translate", "all"):
        from .translate import AnthropicToolLLM

        summary["translate"], details["translate"] = evals.run_translate(
            AnthropicToolLLM(settings.translate_model),
            evals.load_jsonl(evals.EVALS / "translate.jsonl"))
    if a.suite in ("queries", "all"):
        from . import db

        with db.connect() as conn:
            summary["queries"], details["queries"] = evals.run_queries(
                conn, evals.load_jsonl(evals.EVALS / "queries.jsonl"))
    summary = {k: v for k, v in summary.items() if v}
    path = evals.write_run(summary, details, {"extract_model": settings.extract_model,
                                              "translate_model": settings.translate_model,
                                              "agent_model": settings.agent_model})
    print(json.dumps(summary, indent=2))
    print(f"Wrote {path}")
    if a.update_baseline:
        base_path = evals.EVALS / "baseline.json"
        baseline = json.loads(base_path.read_text()) if base_path.exists() else {}
        baseline = {k: v for k, v in baseline.items() if v}
        baseline.update(summary)  # only the suites that just ran
        base_path.write_text(json.dumps(baseline, indent=2) + "\n")
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

    s = sub.add_parser("init-db", help="Apply db/schema.sql (safe to re-run after upgrades)")
    s.set_defaults(fn=cmd_init_db)

    s = sub.add_parser("find", help="Plain-English search, e.g. 'all catholic high schools'")
    s.add_argument("question")
    s.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    s.add_argument("--csv", help="Also save results to this CSV file")
    s.add_argument("-v", "--verbose", action="store_true", help="Show the translated filters")
    s.set_defaults(fn=cmd_find)

    s = sub.add_parser("ask", help="Ask the agent a question (multi-step, cites sources)")
    s.add_argument("question")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("chat", help="Interactive chat with follow-up questions")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_chat)

    s = sub.add_parser("eval", help="Run evals")
    s.add_argument("--suite", choices=["extraction", "translate", "queries", "all"], default="extraction")
    s.add_argument("--check", action="store_true", help="Fail on regression vs baseline")
    s.add_argument("--update-baseline", action="store_true")
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("mcp", help="Run the MCP server (stdio)")
    s.set_defaults(fn=cmd_mcp)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
