-- Postgres + pgvector + earthdistance (no PostGIS needed for radius search)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS cube;
CREATE EXTENSION IF NOT EXISTS earthdistance;

-- One row per school from the NCES Private School Survey (PSS)
CREATE TABLE IF NOT EXISTS schools (
    ppin            TEXT PRIMARY KEY,          -- PSS school id
    name            TEXT NOT NULL,
    address         TEXT,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    religious_group TEXT,                      -- catholic | other_religious | nonsectarian
    affiliation     TEXT,                      -- detailed orientation, e.g. "Roman Catholic", "Jewish"
    level           TEXT,                      -- elementary | secondary | combined
    enrollment      INTEGER,
    website         TEXT,
    pss_year        TEXT,
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS schools_earth_idx ON schools USING gist (ll_to_earth(lat, lon));

-- Facts extracted by the enrichment agent. Every value carries provenance.
CREATE TABLE IF NOT EXISTS school_facts (
    id           BIGSERIAL PRIMARY KEY,
    ppin         TEXT REFERENCES schools(ppin) ON DELETE CASCADE,
    field        TEXT NOT NULL,                -- tuition_max | tuition_min | matriculation | ...
    value_json   JSONB NOT NULL,
    source_url   TEXT NOT NULL,
    quote        TEXT NOT NULL,                -- verbatim text from the page that supports the value
    verified     BOOLEAN NOT NULL DEFAULT false, -- quote was found in the fetched page text
    model        TEXT,
    extracted_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS school_facts_ppin_idx ON school_facts (ppin, field);

-- Crawled page chunks for semantic search (RAG)
CREATE TABLE IF NOT EXISTS page_chunks (
    id         BIGSERIAL PRIMARY KEY,
    ppin       TEXT REFERENCES schools(ppin) ON DELETE CASCADE,
    url        TEXT NOT NULL,
    chunk      TEXT NOT NULL,
    embedding  vector(384),                    -- bge-small-en-v1.5
    fetched_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS page_chunks_hnsw ON page_chunks USING hnsw (embedding vector_cosine_ops);

-- Derived, query-friendly view (latest verified fact per field)
CREATE OR REPLACE VIEW school_summary AS
SELECT s.*,
       (SELECT (f.value_json->>'amount')::numeric FROM school_facts f
         WHERE f.ppin = s.ppin AND f.field = 'tuition_max' AND f.verified
         ORDER BY f.extracted_at DESC LIMIT 1) AS tuition_max,
       (SELECT (f.value_json->>'score')::numeric FROM school_facts f
         WHERE f.ppin = s.ppin AND f.field = 'college_outcome_score' AND f.verified
         ORDER BY f.extracted_at DESC LIMIT 1) AS college_outcome_score
FROM schools s;
