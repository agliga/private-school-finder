# Evals

Shipping AI means shipping feedback loops. Every change to prompts, models, chunking or
scoring is measured here before it merges.

## Extraction suite (`--suite extraction`)

Runs the extractor on **frozen page snapshots** and compares to **hand labels**.

1. Pick a school and freeze its pages: `school-finder snapshot --ppin <PPIN>`
   (writes `snapshots/<PPIN>.json`; commit it so CI is reproducible).
2. Open the school's site yourself and add one line to `labels/extraction.jsonl`:

```json
{"ppin": "A1234567", "name": "Example School", "tuition_max": 32500, "tuition_min": 28000,
 "affiliation": "Roman Catholic", "has_matriculation": true,
 "colleges_sample": ["UC Davis", "Santa Clara University", "Stanford University"],
 "source_url": "https://example.org/tuition", "labeled_on": "2026-11-08"}
```

Use `null` for anything the site does **not** publish. Those rows test that the model
says "not published" instead of guessing (hallucination rate).

Metrics: `tuition_accuracy` (within 2% or $250), `tuition_min_accuracy`,
`hallucination_rate`, `citation_verified_rate` (quote really appears on the cited page),
`college_recall` (share of your sampled colleges the model found), `affiliation_accuracy`.

Target: 40-50 labeled schools, including ~10 that publish no tuition and ~10 with no
college list.

## Translation suite (`--suite translate`)

Checks that plain-English questions become the right filters (`school-finder find`).
Each line of `translate.jsonl` has a question and the expected filters:

```json
{"question": "show me all catholic high schools",
 "expected": {"religious_groups": ["catholic"], "levels": ["secondary"], "limit": 500}}
```

A case passes only if every expected filter matches **and** no other filter was invented
(e.g. adding a city the user never said). `sort`, `limit` and `group_by` are checked only
when listed. Counting questions use `"kind": "count"`. Metric: `translate_accuracy`.
No database needed, so it runs in CI on every push. When `find` gets something wrong,
add that question here.

## Query suite (`--suite queries`)

Each line of `queries.jsonl` is a parent-style question plus schools that must / must not
appear:

```json
{"question": "Catholic high schools within 10 miles of San Jose under $30k",
 "must_include": ["A1234567"], "must_exclude": ["B7654321"]}
```

Metrics: `query_recall`, `exclusion_violation_rate`, `avg_tool_calls`.

## Regression gate

`school-finder eval --suite all --check` compares against `baseline.json` and exits 1
if a metric moves the wrong way by more than 0.05. After an intentional improvement,
run with `--update-baseline` and commit the new baseline. Every run is saved to
`results/` with git SHA and model names.
