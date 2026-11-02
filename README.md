# private-school-finder

Ask in plain English, get private schools that fit, with **every fact cited**:

> "Catholic high schools within 15 miles of San Jose under $30k, best college outcomes first"

The structured basics (location, religious orientation, level, enrollment) come from the
federal **NCES Private School Survey**. What families actually want to know (tuition and
where graduates go to college) is only published on each school's own website, in every
format imaginable. An agent crawls those sites, extracts the facts with a **verbatim quote
and URL for each one**, and code verifies the quote is really on the page before the fact
is ever shown. Anything a school doesn't publish is reported as *not published*, never
estimated.

## How it works

```
NCES PSS CSV ──► Postgres (schools, geo index)
                     │
   find site (Claude + web search) ─► polite crawler (robots.txt, same-domain, ranked links)
                     │
   extraction (Claude tool use → typed schema, quote + URL per fact)
                     │
   provenance check (quote must appear on cited page) ─► school_facts (verified flag)
                     │
   chunk + embed (bge-small, local) ─► pgvector (HNSW)
                     │
   query agent (Claude tool use: search_schools / semantic_search / get_school)
   MCP server (same tools for Claude Code, Cursor, Claude Desktop)
                     │
   evals: frozen page snapshots + hand labels ─► CI regression gate
```

| Piece | File |
|---|---|
| PSS loader | `src/school_finder/pss.py` |
| Schema (pgvector + earthdistance) | `db/schema.sql` |
| Crawler | `src/school_finder/crawl.py` |
| Extraction + provenance check | `src/school_finder/extract.py` |
| Categories (tuition bands, college outcome score) | `src/school_finder/scoring.py` |
| Enrichment pipeline | `src/school_finder/enrich.py` |
| Agent tools / query agent | `src/school_finder/tools.py`, `agent.py` |
| MCP server | `src/school_finder/mcp_server.py` |
| Eval harness | `src/school_finder/evals.py`, `evals/` |

## Categories

- **Cost:** published annual tuition → bands (under $15k, $15k-$30k, $30k-$45k, $45k+, not published).
- **Religious affiliation:** PSS orientation, refined by what the school says about itself.
- **College outcomes:** share of colleges on the school's published matriculation list that
  are on `data/selective_colleges.txt` (edit it, it's a choice, not a fact). Few schools publish
  true acceptance rates, so this is a transparent proxy shown with its source, not a ranking.

## Quick start

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY
docker compose up -d            # Postgres + pgvector, schema auto-loaded
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
set -a; source .env; set +a

# 1. Download the PSS public-use CSV from https://nces.ed.gov/surveys/pss/pssdata.asp
#    into data/raw/, check the codebook column names, then load the San Jose area:
school-finder load-pss data/raw/pss2324_pu.csv --state CA --year 2023-24 --county-zip-prefix 950 951

# 2. Enrich a few schools (find site, crawl, extract with citations, embed)
school-finder enrich --city "San Jose" --limit 5

# 3. Ask
school-finder ask "Catholic high schools near San Jose under \$30k" -v

# 4. MCP: add to your client config as  {"command": "school-finder", "args": ["mcp"]}
```

## Evals

See [`evals/README.md`](evals/README.md). Short version: freeze a school's pages with
`school-finder snapshot --ppin ...`, hand-label what the site really says, then

```bash
school-finder eval --suite extraction --check
```

reports tuition accuracy, hallucination rate, citation-verified rate and college recall,
saves the run with git SHA and model names, and fails CI if anything regresses.

## Tests

```bash
pytest -q          # unit tests run offline; DB tests run when Postgres is up
ruff check .
```

## Roadmap

- [ ] Label 40-50 Santa Clara County schools; first baseline
- [ ] Query eval set (20 parent-style questions)
- [ ] Scheduled re-crawl with change detection (tuition changed, new college list)
- [ ] Hybrid retrieval (BM25 + vectors) and a reranker, compared in evals
- [ ] Small web UI / SwiftUI app

## Data and ethics

Only schools' own websites are crawled (no directory sites), robots.txt is respected,
requests are rate-limited, and every displayed fact links to its source.

MIT License.
