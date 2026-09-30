# Private offline processing

Set `OFFLINE_MODE=true` to process uploaded PDFs and answer questions with local
Docling/EasyOCR, local Ollama embeddings, and a local Ollama answer model. The
normal Typhoon/Gemini configuration remains available when this flag is false.
Public website collection requires internet and returns HTTP 403 in offline mode.

## Prepare while connected

1. Keep PostgreSQL/pgvector and Ollama on `localhost`. Run the existing Docker
   services and make sure the configured embedding model is already in Ollama.
   The Compose file binds PostgreSQL and Redis to `127.0.0.1`; existing
   containers must be recreated for changed port bindings to take effect.
2. Pull a local answer model once, for example `ollama pull gemma3:4b`. The
   [Ollama Gemma 3 library](https://ollama.com/library/gemma3) lists this model.
3. Install Docling and EasyOCR in a separate Python environment, and prefetch
   the Docling/TableFormer and Thai/English EasyOCR weights. The Step 4
   experiment used `work/step4_local_ocr/.venv` and its `models` directory in
   the Codex task workspace. At runtime the worker sets offline cache flags,
   disables Docling remote services and plugins, and forbids model downloads.

Set these environment variables before starting the API (or add them to your
ignored `.env`):

```text
OFFLINE_MODE=true
OFFLINE_LLM_MODEL=gemma3:4b
EMBED_MODEL=bge-m3
LOCAL_OCR_PYTHON=C:/path/to/docling-venv/Scripts/python.exe
LOCAL_OCR_MODELS_DIR=C:/path/to/prefetched/docling-models
LOCAL_OCR_EASYOCR_CACHE_DIR=C:/path/to/prefetched/easyocr-cache
PRIVATE_DATA_DIR=C:/Users/you/AppData/Local/financial-rag-private
```

`PRIVATE_DATA_DIR` must be outside OneDrive. New uploaded files, temporary PDF
images, DuckDB data, and Q&A logs use that directory. PostgreSQL must also be
local. Files already saved in the old project upload directory are not migrated
automatically; inspect and move or remove those separately if they contain
confidential material.

Start the API with `python -m backend.main`. Offline startup fails if the local
OCR environment, model weights, answer model, or embedding model are missing.
The API binds to `127.0.0.1`. Its Python process and the Docling worker reject
external DNS, TCP, and UDP connections while still allowing localhost services.
There is no cloud OCR, generation, or web search fallback in this mode.
The manual knowledge-graph endpoints and cloud Ragas evaluation are disabled.

## Reproduce the private workflow check

With the offline environment active, run:

```text
python -m scripts.test_private_offline --pdf path/to/synthetic-one-page.pdf --output path/to/offline-result.json
```

The script uses the real API upload route, waits for local OCR and indexing,
asks a question, checks the answer's PDF page source, confirms external DNS is
blocked, checks an external TCP connection and browser origin, and confirms
that public scraping and graph access are disabled. It deletes the test
document after the run. Use a synthetic PDF whose answer appears clearly in
prose. The result JSON records timings and source page metadata.

## Limits

Step 4 measured Docling/EasyOCR at 10/16 correct labeled table cells on the
selected development pages, compared with 16/16 for cached Typhoon/Gemini.
Dense rotated tables and charts remain unreliable. Offline processing proves
data locality, not equal extraction accuracy. OCR values remain marked as
machine extracted and should be checked against the PDF before financial use.
The socket guard covers this Python API and its OCR worker; it does not control
unrelated programs or operating-system cloud sync.

## Recorded local run (2026-09-26)

On a synthetic one-page image PDF, the private workflow test reported:

| Check | Result |
| --- | --- |
| Upload response | Queued in 0.84 seconds |
| Local OCR and indexing | Page 1 indexed; document completed in 59.65 seconds |
| Local answer | “this computer,” with a PDF page 1 source |
| Total elapsed | 62.87 seconds, including the local model answer |
| External DNS and TCP | Blocked by the API's socket guard |
| External browser origin | Rejected by CORS |
| Public scraping and manual graph routes | HTTP 403 |
| Test document | Deleted after the run |

The test used Docling with prefetched local weights, Ollama `gemma3:4b`, and
Ollama `bge-m3`. The synthetic PDF and machine-readable result are in the
Codex task workspace under `work/step6_offline/` and
`outputs/step6_offline_2026-09-26/result.json`. This is a locality test on one
page, not a throughput or accuracy estimate. It blocks external connections
from the app and worker processes; it is not an operating-system-wide firewall
test.

The running Docker port bindings could not be inspected from this workspace,
so the Compose loopback change is recorded as configuration rather than a
verified property of the existing containers.
