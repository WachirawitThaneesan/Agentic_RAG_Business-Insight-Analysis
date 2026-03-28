# Project_1

This repository is a FastAPI app for:

- uploading PDFs and images
- OCR with Typhoon OCR
- extracting tables and raw OCR pages
- Thai text cleaning and chunking
- storing chunks in Postgres/pgvector
- syncing table data into DuckDB
- scraping websites with Playwright

## OCR pipeline

The OCR path in the app is now:

- PDF page -> render to PNG
- PNG -> Typhoon OCR
- Markdown -> text blocks + tables

For uploaded PDFs, every page goes through Typhoon OCR. The old native-text skip path is removed.

## Scraping challenge solvers

The Playwright worker now includes:

- Cloudflare challenge handling
- reCAPTCHA audio solving

### reCAPTCHA behavior

The solver flow is:

1. Click the reCAPTCHA circle first.
2. If that does not solve it, open the audio challenge.
3. Download the audio.
4. Convert it with FFmpeg.
5. Transcribe it and submit the answer.

Implementation:

- `backend/services/recaptcha_solver.py`

### Cloudflare behavior

The solver flow is:

1. Detect the Cloudflare challenge frame.
2. Click the checkbox area like a human.
3. Wait for either `cf_clearance` or a Turnstile token.

Implementation:

- `backend/services/cloudflare_solver.py`

The worker calls these solvers centrally from:

- `backend/services/pw_worker.py`

These solvers are used by the scraping pipeline:

- `backend/routes/scraping.py`
- `backend/services/scraper.py`
- `backend/services/pw_worker.py`

## Python environments

Use separate environments:

- Full app environment: `requirements.txt`
- OCR-only utility environment: `requirements.ocr.txt`

## Full app setup

Create a fresh virtual environment and install:

```powershell
python -m venv .venv_app
python -m pip --python .\.venv_app install pip==26.0
python -m pip --python .\.venv_app install -r requirements.txt
python -m playwright install chromium
```

## Required services

The app needs more than Python packages:

1. PostgreSQL with pgvector
2. Redis
3. Ollama
4. Typhoon OCR API access

Start Postgres and Redis with:

```powershell
docker compose up -d
```

## Environment variables

Create a `.env` file with your own values:

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

## Run the app

```powershell
.\.venv_app\Scripts\Activate.ps1
python -m backend.main
```

## Extra system dependencies

For the reCAPTCHA audio solver, install:

- `ffmpeg`
- `ffprobe`

On Windows, either:

- put `ffmpeg.exe` and `ffprobe.exe` in the project working directory, or
- add them to your system `PATH`

## Notes

- `.env` is gitignored and should not be committed.
- If someone else pulls this repo, they must create their own `.env`.
- Thai text may display incorrectly in PowerShell even when saved files are valid UTF-8.
