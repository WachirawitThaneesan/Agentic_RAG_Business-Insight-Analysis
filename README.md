# Agentic RAG Business Insight Analysis (Intelligent Financial Data Agent)

This repository contains a FastAPI-based **Intelligent Financial Data Agent** that implements an advanced Agentic Retrieval-Augmented Generation (RAG) system. It is designed to extract, process, and analyze Thai financial documents using a combination of LLMs, deterministic SQL queries, and robust web scraping techniques.

## Key Features

### 1. Agentic RAG Architecture (ReAct & LangGraph)
- **Hybrid Retrieval Strategy**: Dynamically routes queries between a Fast-Path (direct vector search) and an Agentic ReAct Loop (complex reasoning).
- **LangGraph Orchestrator**: Manages state and tool execution flows for the agent.
- **Self-Correction Logic**: Built-in mechanisms (`backend/services/self_correction.py`) to validate and correct outputs before returning them to the user.

### 2. Multi-Tool Integration
The agent utilizes specialized tools (`backend/services/tools.py`) to answer queries:
- `vector_search`: For semantic similarity search using PostgreSQL + pgvector.
- `sql_query`: For precise financial metric lookups and aggregations using DuckDB.
- `multi_hop`: For complex questions requiring reasoning across multiple documents.
- `tavily_search`: For real-time web search capabilities.

### 3. Advanced Data Ingestion & OCR
- **Single-Pass Typhoon OCR**: Converts PDF pages to PNG and processes them through OpenTyphoon API for high-accuracy Thai text and table extraction.
- **Thai Text Normalization**: Custom post-processing and cleaning routines (`thai_cleaner.py`, `thai_postprocessor.py`) ensure data quality before embedding.
- **Semantic Chunking**: Intelligent text chunking strategies for optimal vector storage.

### 4. Structured Data Warehouse
- **DuckDB Integration**: Automatically syncs extracted table data from documents into a fast, in-process DuckDB warehouse for accurate SQL querying.

### 5. Web Scraping with Anti-Bot Solvers
Robust Playwright-based scraper (`backend/services/pw_worker.py`) capable of bypassing protections:
- **Cloudflare Challenge Solver**: Detects and naturally solves Turnstile/Cloudflare challenges.
- **reCAPTCHA Audio Solver**: Falls back to downloading and transcribing audio challenges via FFmpeg when visual challenges fail.

### 6. Background Processing & Evaluation
- **Celery & Redis**: Asynchronous task queue for heavy workloads like OCR and scraping.
- **Ragas Evaluation**: Built-in tools to measure system performance (Context Precision, Recall, Faithfulness).

## System Requirements

- **Python**: 3.10+
- **PostgreSQL**: With `pgvector` extension
- **Redis**: For Celery message broker
- **Ollama**: Local LLM runner (e.g., Qwen2.5)
- **DuckDB**: (In-process, installed via pip)
- **FFmpeg**: Required on system PATH for the reCAPTCHA audio solver.

## Setup & Installation

### 1. Environment Variables
Create a `.env` file in the root directory:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5436/ragdb
DATABASE_URL_SYNC=postgresql://postgres:postgres@localhost:5436/ragdb
REDIS_URL=redis://localhost:6379/0
OLLAMA_HOST=http://localhost:11434
EMBED_MODEL=nomic-embed-text:latest
OLLAMA_LLM_MODEL=qwen2.5:14b
TYPHOON_API_KEY=your_key_here
TYPHOON_OCR_ENDPOINT=https://api.opentyphoon.ai/v1/ocr
TYPHOON_OCR_MODEL=typhoon-ocr
APP_HOST=0.0.0.0
APP_PORT=8000
```

### 2. Services (Docker)
Start the required PostgreSQL (with pgvector) and Redis services:
```powershell
docker compose up -d
```

### 3. Python Environment
Create a virtual environment and install dependencies:
```powershell
python -m venv .venv_app
.\.venv_app\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Running the Application

### Start the FastAPI Server
```powershell
.\.venv_app\Scripts\Activate.ps1
python -m backend.main
```
The API will be available at `http://localhost:8000`. The frontend SPA (if built) is served at the root `/`.

### Start Celery Worker (Optional but recommended for async tasks)
```powershell
.\.venv_app\Scripts\Activate.ps1
celery -A backend.tasks worker --loglevel=info -P solo
```

## Project Structure
- `backend/main.py`: FastAPI entrypoint.
- `backend/routes/`: API endpoint definitions (documents, scraping, query, warehouse).
- `backend/services/`: Core logic (Agent, OCR, Scraping, RAG, DuckDB, Self-Correction).
- `backend/tasks.py`: Celery tasks for background processing.
- `frontend/`: (Optional) Static files for the user interface.
