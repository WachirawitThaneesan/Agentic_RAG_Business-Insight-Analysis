# Intelligent Financial Data Agent (Agentic RAG)

A FastAPI-based **Agentic Retrieval-Augmented Generation (RAG)** system for extracting,
processing, and analyzing **Thai financial documents**. Its configured online path
uses Gemini for generation and tool selection, Typhoon for prose OCR, and Gemini
for table extraction. Private offline mode uses local OCR and Ollama models.
It combines deterministic SQL over a DuckDB warehouse, semantic search over
PostgreSQL/pgvector, and a knowledge graph — routed by a tool-using agent with an
answer self-correction step.

---

## Evaluation Update — 8 October 2026

The Gemini-assisted development evaluation now covers **all 498 questions**.
Eight answer/evidence metrics exceed 80% under conservative aggregation across
the full set (**85.96–96.69%**). The
[English research report](docs/GEMINI_RAG_FULL498_REPORT_2026-10-08.md) presents
the results and explains complete-answer and numerical relationship challenges
as future work. These are AI-reviewed development results; the full quality
objective and unseen-report evaluation remain open.

See the [updated plan and next steps](docs/EVALUATION_NEXT_STEPS_2026-10-08.md)
and [published evidence package](TestFile/published_2026-10-08/README.md) for
metric coverage, frozen runs, candidate decisions, and checksums. Docling has
not started.

## Key Features

### 1. Agentic RAG — ReAct loop with deterministic routing
- **ReAct agent** ([`backend/services/agent.py`](backend/services/agent.py)) — a plain
  LLM ReAct loop (Thought → Action → Observation → Final Answer) that calls tools via
  the configured generation provider. The online template selects Vertex Gemini;
  offline mode selects Ollama. This is a hand-rolled ReAct loop, not LangGraph.
- **Deterministic query router** ([`backend/services/query_router.py`](backend/services/query_router.py))
  — classifies each question by keyword signals and picks the right tool up front. On a
  high-confidence match it **forces the first tool call** rather than trusting the LLM to
  choose, which sharply improves tool selection with a local model.
- **Answer self-correction** ([`backend/services/answer_verifier.py`](backend/services/answer_verifier.py))
  — after the agent drafts a `Final Answer`, a second LLM pass checks that every fact is
  **grounded** in the tool observations and that the answer is **on-topic**; if not, the
  agent can regenerate once with the critique. A final deterministic grounding
  guard checks supporting source locations and numeric evidence. Available tools
  are filtered against indexed data, and searches have a bounded call budget.
  Toggle the optional LLM review via `AGENT_SELF_CORRECTION`.
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
- **Typhoon OCR** reads normal Thai text; when configured, **Gemini** extracts tables.
- Landscape two-up pages are split at a detected gutter; sideways bank tables
  are rotated using PDF text *direction* only (never embedded-text values).
  Crop/rotation metadata remains attached to the physical PDF page. A failed
  region makes the page fail rather than fabricating a table.
- Uploaded and scraped PDFs use the same saved-file queue and record each physical
  PDF page in `document_pages`. Scraped PDF registration returns `pending`; OCR
  continues in the background and the Documents view shows page failures.
  Raw OCR is saved
  before embedding/table indexing, so a later failure is reported as `partial`
  with its page number and stage instead of silently losing the OCR. The document
  API exposes `page_statuses` and `raw_ocr_pages` for inspection. Page numbers
  refer to the PDF's page order; printed page numbers are not required.
- Raw OCR and quality-warning artifacts are for inspection and are excluded from
  answer retrieval. Table values that fail internal checks are excluded from
  structured search and DuckDB. Answer sources link to the physical PDF page;
  OCR values remain unverified against the original image until reviewed.
  SQL aggregates and legacy graph results can have unresolved page attribution.
- PDF ingestion skips optional Ollama chunk summaries; OCR, embeddings, and
  structured tables still run, without a summary outage blocking a page.
- Malformed multi-row financial HTML headers are normalized into year and change
  columns, and table IDs include the PDF page/index to avoid warehouse overwrites.
- **OCR table self-correction** ([`backend/services/self_correction.py`](backend/services/self_correction.py))
  validates column counts / numeric cells and repairs unit-column shifts.
- **Thai text normalization** ([`thai_cleaner.py`](backend/services/thai_cleaner.py),
  [`thai_postprocessor.py`](backend/services/thai_postprocessor.py)) and semantic chunking.

### 5. Knowledge Graph (Hyper-Extract)
- [`backend/services/graph_service.py`](backend/services/graph_service.py) builds a
  Knowledge Abstract per document and exposes it via the `graph_search` tool and the
  `/api/graphs` routes.

### 6. Public PDF Discovery
- The bounded [PDF crawler](backend/services/pdf_discovery.py) follows report links
  and sitemaps, checks robots.txt, verifies PDF bytes, and downloads reports with
  source URLs and SHA-256 hashes. For PDF-only collection, Playwright renders a
  page only when plain HTTP finds no PDF; keyword search also uses Playwright.
  Requests for images still use the legacy browser worker. The crawler does not
  try to bypass sites that deny access.
- See [discovery measurements and limits](docs/pdf-discovery.md). Public collection
  requires internet access and is disabled in offline mode.

### 7. Background Processing & Evaluation
- PDF uploads are streamed to unique saved files, return a document ID quickly,
  and run in a single API-owned background queue. PostgreSQL page checkpoints
  let pending/interrupted jobs resume after API restart. The API owns DuckDB;
  a second Celery process must not write the same DuckDB file.
- The OCR viewer loads a 25-page status window and one selected page's PDF
  image, raw OCR, parsed tables, final stored rows, and quality reasons.
- **Celery + Redis** ([`backend/tasks.py`](backend/tasks.py)) remain for
  knowledge-graph builds and scraping. The old Celery `process_document` task
  is retired because it bypassed the page-level quality gate.
- **Ragas evaluation** ([`backend/services/evaluation.py`](backend/services/evaluation.py)) —
  a live eval loop that runs the real agent over a golden set and scores it, tracking
  results over time for before/after comparison (see [Evaluation](#evaluation)).

---

## System Requirements
- **Python** 3.10+
- **PostgreSQL** with the `pgvector` extension
- **Redis** (Celery broker)
- **Ollama** for local embeddings and optional offline answer generation
- **DuckDB** (in-process, via pip)
- **FFmpeg** on PATH only for the legacy browser challenge helper

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

For private processing without cloud calls, see [offline mode](docs/offline-mode.md).

### API server
```bash
python -m backend.main
```
API at `http://localhost:8000` (docs at `/docs`). The frontend SPA, if built, is served at `/`.

### Celery worker (for scraping / graph builds; PDF OCR runs in the API)
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
- The Ragas judge uses Typhoon cloud; embeddings use the configured local
  `EMBED_MODEL`, shared with ingestion. Saved Thai retrieval experiments use
  `bge-m3`; the environment template retains the original Nomic default.

For the detailed October 2026 update, verified software tests, saved retrieval
comparisons, local OCR measurements, and remaining work, see
[the auto1 update](docs/auto1-update-2026-10-01.md).

For the separate OCR diagnostic, run `python scripts/score_ocr_cells.py --split all`.
The 16 currently labeled table cells are a small exact-row/column test:
13/16 pass the cached OCR check, while the three bank-page-46 position cells
remain OCR failures. This is not whole-report accuracy. Four chart facts are
labeled but category/value extraction remains unresolved.

For held-out retrieval and answer results, long-document recovery, and the
offline presentation path, see [Step 8 thesis evaluation](docs/thesis-evaluation.md)
and the [demo runbook](docs/thesis-demo.md).

---

## Project Structure
```
backend/
  main.py                  FastAPI entrypoint (routes, CORS, static files)
  config.py                Settings (loaded from .env)
  database.py              Async SQLAlchemy engine/session
  models.py                ORM models
  tasks.py                 Celery tasks (scraping, graph build; legacy OCR retired)
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
