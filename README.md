# Intelligent Financial Data Agent (Agentic RAG)

A FastAPI-based **Agentic Retrieval-Augmented Generation (RAG)** system for extracting,
processing, and analyzing **Thai financial documents**. It combines a local LLM
(via Ollama), deterministic SQL over a DuckDB warehouse, semantic search over
PostgreSQL/pgvector, and a knowledge graph — routed by a tool-using agent with an
answer self-correction step.

---

## Key Features

### 1. Agentic RAG — ReAct loop with deterministic routing
- **ReAct agent** ([`backend/services/agent.py`](backend/services/agent.py)) — a plain
  LLM ReAct loop (Thought → Action → Observation → Final Answer) that calls tools via
  direct Ollama API calls. *(Note: this is a hand-rolled ReAct loop, not LangGraph.)*
- **Deterministic query router** ([`backend/services/query_router.py`](backend/services/query_router.py))
  — classifies each question by keyword signals and picks the right tool up front. On a
  high-confidence match it **forces the first tool call** rather than trusting the LLM to
  choose, which sharply improves tool selection with a local model.
- **Answer self-correction** ([`backend/services/answer_verifier.py`](backend/services/answer_verifier.py))
  — after the agent drafts a `Final Answer`, a second LLM pass checks that every fact is
  **grounded** in the tool observations and that the answer is **on-topic**; if not, the
  agent regenerates once with the critique. Fails *open* so a flaky judge never blocks a
  valid answer. Toggle via `AGENT_SELF_CORRECTION`.
  *(Distinct from [`self_correction.py`](backend/services/self_correction.py), which
  validates OCR **table** structure — see feature 4.)*

### 2. Five agent tools ([`backend/services/tools.py`](backend/services/tools.py))
| Tool | Purpose | Backend |
|------|---------|---------|
| `sql_query` | Numbers, ratios, rankings, tabular lookups | DuckDB warehouse |
| `vector_search` | Policies, strategy, ESG, qualitative text | PostgreSQL + pgvector |
| `multi_hop` | Complex questions split into sub-queries | SQL + Vector |
| `graph_search` | Entity relationships, ownership, officer roles | Knowledge graph |
| `tavily_search` | Web fallback (gated until internal tools are tried) | Tavily API |

### 3. Structured Data Warehouse (DuckDB)
- Extracted tables are synced into a DuckDB warehouse
  ([`backend/services/duckdb_warehouse.py`](backend/services/duckdb_warehouse.py)):
  - `fact_financial_metrics` — year-based figures (one row per cell), with a parsed
    `numeric_value`.
  - `dim_table_rows` — non-year "lookup" data (EAV/long format), with a pre-parsed
    `col_value_num` so the agent never hand-writes `CAST(REPLACE(...))`.
  - `v_table_rows_wide` — a **pivot view** turning the EAV rows into one row per
    company/attribute, so cross-attribute questions avoid correlated sub-queries.

### 4. Data Ingestion & OCR
- **Typhoon OCR** converts PDF pages to images and extracts Thai text + tables.
- **OCR table self-correction** ([`backend/services/self_correction.py`](backend/services/self_correction.py))
  validates column counts / numeric cells and repairs unit-column shifts.
- **Thai text normalization** ([`thai_cleaner.py`](backend/services/thai_cleaner.py),
  [`thai_postprocessor.py`](backend/services/thai_postprocessor.py)) and semantic chunking.

### 5. Knowledge Graph (Hyper-Extract)
- [`backend/services/graph_service.py`](backend/services/graph_service.py) builds a
  Knowledge Abstract per document and exposes it via the `graph_search` tool and the
  `/api/graphs` routes.

### 6. Web Scraping with Anti-Bot Solvers
- Playwright scraper ([`backend/services/pw_worker.py`](backend/services/pw_worker.py))
  with a Cloudflare/Turnstile solver and a reCAPTCHA audio-transcription fallback
  (requires FFmpeg on PATH).

### 7. Background Processing & Evaluation
- **Celery + Redis** ([`backend/tasks.py`](backend/tasks.py)) for OCR, scraping, and
  knowledge-graph builds.
- **Ragas evaluation** ([`backend/services/evaluation.py`](backend/services/evaluation.py)) —
  a live eval loop that runs the real agent over a golden set and scores it, tracking
  results over time for before/after comparison (see [Evaluation](#evaluation)).

---

## System Requirements
- **Python** 3.10+
- **PostgreSQL** with the `pgvector` extension
- **Redis** (Celery broker)
- **Ollama** (e.g. `qwen2.5:14b` + `nomic-embed-text`)
- **DuckDB** (in-process, via pip)
- **FFmpeg** on PATH (for the reCAPTCHA audio solver)

## Setup

### 1. Environment variables
Copy the template and fill in your values (`.env` is git-ignored):
```bash
cp .env.example .env
```

### 2. Services (Docker)
```bash
docker compose up -d      # PostgreSQL (pgvector) + Redis
```

### 3. Python environment
```bash
python -m venv env
# Windows:  env\Scripts\activate     |  Unix: source env/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Running

### API server
```bash
python -m backend.main
```
API at `http://localhost:8000` (docs at `/docs`). The frontend SPA, if built, is served at `/`.

### Celery worker (for async OCR / scraping / graph builds)
```bash
celery -A backend.tasks worker --loglevel=info -P solo
```

## Evaluation

Run the live Ragas evaluation over the golden set (drives the real agent end-to-end):
```bash
python -m backend.services.evaluation --live --label baseline
```
- Golden questions + ground truths: [`backend/eval/golden_set.json`](backend/eval/golden_set.json)
- Per-run scores and a cumulative history (with deltas vs the previous run) are written to
  `backend/eval/results/` (git-ignored).
- The Ragas judge defaults to Typhoon cloud; embeddings use the same local Nomic model as
  ingestion.

---

## Project Structure
```
backend/
  main.py                  FastAPI entrypoint (routes, CORS, static files)
  config.py                Settings (loaded from .env)
  database.py              Async SQLAlchemy engine/session
  models.py                ORM models
  tasks.py                 Celery tasks (OCR, scraping, graph build)
  routes/                  API endpoints (documents, scrape, query, chunks, warehouse, graph)
  services/
    agent.py               ReAct agent loop
    query_router.py        Deterministic tool router
    answer_verifier.py     Answer self-correction (grounding/relevance)
    tools.py               The five agent tools
    rag.py                 Vector search + text-to-SQL helpers
    duckdb_warehouse.py    DuckDB schema, loading, pivot view, SQL execution
    graph_service.py       Knowledge-graph build/search (Hyper-Extract)
    ocr.py / table_*.py    OCR + table extraction pipeline
    self_correction.py     OCR table validation & repair
    thai_*.py              Thai text cleaning/normalization
  eval/
    golden_set.json        Curated eval questions + ground truths
    results/               Generated eval outputs (git-ignored)
frontend/                  Static SPA assets (optional)
scripts/                   Ad-hoc utilities (db checks, model listing)
experiments/               One-off / exploratory scripts
scratch/                   Local debug dumps (git-ignored)
```
