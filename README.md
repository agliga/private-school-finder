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

## Setup (macOS)

**Prerequisites:** Docker (Docker Desktop, or Colima + Docker CLI), Python 3.11+, and an
Anthropic API key.

```bash
git clone https://github.com/agliga/private-school-finder.git
cd private-school-finder

# Python 3.12 via uv (prebuilt, no compiler needed)
curl -LsSf https://astral.sh/uv/install.sh | sh     # once; then open a new terminal
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

# API key
cp .env.example .env            # paste your key into ANTHROPIC_API_KEY

# Database: Postgres + pgvector, schema loads automatically on first start
open -a Docker                  # or: colima start
docker compose up -d
```

Every new terminal:

```bash
cd private-school-finder
source .venv/bin/activate
set -a; source .env; set +a
docker compose up -d            # no-op if already running
```

## Usage

### 1. Download the school list (NCES Private School Survey)

```bash
mkdir -p data/raw && cd data/raw
curl -LO https://nces.ed.gov/surveys/pss/zip/pss2122_pu_csv.zip   # 2021-22 release
unzip pss2122_pu_csv.zip && ls
cd ../..
```

If that URL 404s or a newer year is out, download the **Text** ZIP for the latest year from
https://nces.ed.gov/surveys/pss/pssdata.asp.

### 2. Load schools into Postgres

Check the column names first (they can change between releases; see `src/school_finder/pss.py`):

```bash
head -1 data/raw/*.csv | tr ',' '\n' | grep -iE "^(ppin|pinst|pcity|relig|orient|level|numstuds|lat|lon)"
```

Load California schools in ZIPs starting 950/951 (San Jose area):

```bash
school-finder load-pss data/raw/<file>.csv --state CA --year 2021-22 --county-zip-prefix 950 951
```

Verify (`count(lat)` should be close to `count(*)`; if it is 0 the release has no coordinates
and radius search won't work yet):

```bash
docker compose exec db psql -U schools -c "select count(*), count(lat) from schools;"
docker compose exec db psql -U schools -c "select ppin, name, city, religious_group from schools limit 10;"
```

### 3. Search in plain English

`find` turns a question into structured filters with one Claude call, runs them as SQL and
prints a table. It works right after loading. No enrichment needed (tuition and college
columns appear once schools are enriched).

```bash
school-finder find "show me all catholic high schools"
school-finder find "Jewish schools in San Jose"
school-finder find "non-religious high schools within 5 miles of Palo Alto"
school-finder find "special education schools in Sunnyvale"
school-finder find "the biggest private high schools"
school-finder find "how many catholic schools are in each city"     # counts
```

Example output (illustrative):

```
Showing catholic high schools, sorted by name

#  School                        City      Level  Affiliation     Students
-  ----------------------------  --------  -----  --------------  --------
1  St. Sample High School        Campbell  High   Roman Catholic  1,200
...
12 schools matched
```

Options: `-v` shows the filters Claude chose, `--csv out.csv` saves the results,
`--json` prints JSON.

What it understands: religion (Catholic, other religious, nonsectarian/secular), specific
denominations (Jewish, Lutheran, Baptist, Islamic, Episcopal...), level (high, elementary/
middle, K-12), city ("in X"), distance ("near X", "within N miles of X"), school type
(special education, special emphasis, conservative Christian), size, name ("Montessori"),
tuition and college outcomes (enriched schools), sorting ("biggest", "closest", "cheapest"),
and "how many" breakdowns.

For back-and-forth questions, use chat. Follow-ups keep the earlier filters:

```bash
school-finder chat
> catholic high schools near San Jose
> only the ones with more than 500 students
> which of those are in Campbell?
```

**Upgrading from an earlier version?** Run `school-finder init-db`, then re-run `load-pss` so
denominations and school types are filled in.

### 4. Enrich schools (uses the API)

Finds each school's website, crawls the relevant pages, extracts tuition / affiliation /
college lists with a quote + URL per fact, verifies the quotes, and embeds the pages.

```bash
school-finder enrich --city "San Jose" --limit 5
school-finder enrich --ppin A1234567 B7654321      # specific schools
```

Each school prints one JSON line; `"status": "ok"` with `"verified": {"tuition": true, ...}`
means it worked. See what was extracted:

```bash
docker compose exec db psql -U schools -c \
  "select s.name, f.field, f.value_json, f.verified, f.source_url from school_facts f join schools s using (ppin);"
```

Cost: a few cents per school with the default Haiku extraction model.

### 5. Ask open-ended questions

```bash
school-finder ask "Catholic high schools near San Jose under \$30k" -v
```

`-v` prints the tool calls the agent made. Answers cite sources; anything a school doesn't
publish is reported as "not published".

### 6. Use from Claude Code, Cursor or Claude Desktop (MCP)

Add to your MCP client config (use your absolute path):

```json
{
  "school-finder": {
    "command": "/absolute/path/to/private-school-finder/.venv/bin/school-finder",
    "args": ["mcp"],
    "env": { "DATABASE_URL": "postgresql://schools:schools@localhost:5432/schools" }
  }
}
```

Tools exposed: `search_schools`, `count_schools`, `semantic_search`, `get_school`.

### 7. Run evals

```bash
school-finder eval --suite translate              # question -> filters accuracy (no DB needed)
school-finder snapshot --ppin <PPIN>              # freeze that school's pages
# hand-label it in evals/labels/extraction.jsonl (format in evals/README.md)
school-finder eval --suite extraction             # score
school-finder eval --suite extraction --update-baseline
git add evals && git commit -m "Add eval labels" && git push
```

CI runs the eval on every push (needs the `ANTHROPIC_API_KEY` repo secret under
Settings > Secrets and variables > Actions) and fails if a metric regresses.

### Command reference

| Command | What it does |
|---|---|
| `school-finder load-pss <csv> [--state CA] [--county-zip-prefix 950 951]` | Import schools from the PSS file |
| `school-finder enrich [--city X \| --ppin ...] [--limit N] [--no-embed]` | Find site, crawl, extract, verify, embed |
| `school-finder snapshot [--city X \| --ppin ...]` | Freeze pages for evals |
| `school-finder init-db` | Apply/upgrade the database schema (safe to re-run) |
| `school-finder find "<question>" [-v] [--csv FILE] [--json]` | Plain-English search, printed as a table |
| `school-finder chat [-v]` | Interactive chat with follow-up questions |
| `school-finder ask "<question>" [-v]` | One-off open-ended question (multi-step agent, cites sources) |
| `school-finder eval [--suite extraction\|translate\|queries\|all] [--check] [--update-baseline]` | Run evals |
| `school-finder mcp` | Start the MCP server (stdio) |

Settings live in `.env`: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `EXTRACT_MODEL`,
`TRANSLATE_MODEL`, `AGENT_MODEL`, `EMBED_MODEL`, `CRAWL_USER_AGENT`.

## Troubleshooting

| Error | Fix |
|---|---|
| `unknown shorthand flag: 'd' in -d` | Docker Compose plugin missing: `brew install docker-compose`, then `mkdir -p ~/.docker/cli-plugins && ln -sfn "$(brew --prefix)/opt/docker-compose/bin/docker-compose" ~/.docker/cli-plugins/docker-compose` |
| `failed to connect to the docker API ... docker.sock` | Docker isn't running: `open -a Docker` or `colima start` |
| `docker-credential-desktop: executable file not found` | Leftover Docker Desktop setting: remove the `"credsStore"` line from `~/.docker/config.json` (keep the JSON valid) |
| `requires a different Python: 3.9.6 not in '>=3.11'` | macOS system Python is too old: use `uv venv --python 3.12` (see Setup) |
| `brew install python` fails with `C compiler cannot create executables` | Use uv instead, or reinstall Command Line Tools: `sudo rm -rf /Library/Developer/CommandLineTools && xcode-select --install` |
| `pip: command not found` inside the venv | uv venvs don't include pip; use `uv pip install ...` |
| `Unknown place '...'` | The city has no loaded schools to center on: add it to `PLACES` in `src/school_finder/db.py`, or ask "in <city>" instead of "near" |
| `column "typology" does not exist` | Run `school-finder init-db` (schema upgrade), then re-run `load-pss` |

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
