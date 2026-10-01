# Runtime repairs and verification — results collected 1–2 October 2026

Detailed Thai explanation: [verification report](../../docs/auto1-verification-2026-10-02.md).

## Result ledger

- `diagnostic_v1`: interrupted/incomplete; not a completed accuracy result.
- `diagnostic_v2`–`diagnostic_v7`: all saved development iterations. v3 was affected by service/network failures. Final v7: **14/15**, 25 SDK attempts / 22 successful calls, 58.4 seconds. Source reference unchanged from the prior reviewed v3 manifest.
- `offline_v1`: interrupted; `offline_v2`: page-render API crash; `offline_v3`: renderer repaired, five pages indexed and image HTTP 200, but **answer incorrect/abstained (0/1)**. No full offline success claim.
- `fresh_thai_pilot`: frozen original outputs on PTT/PTTEP, 768 physical PDF pages, 1,969 chunks, 16 questions. Original v1 app fact+source-page score **10/16**, BM25+Gemini **11/16**. Page Hit@5: BM25 13/16, dense 10/16, app 16/16.
- `fresh_rescore_v2`: separate corrected evaluation of identical saved answers: app **12/16**, BM25+Gemini **11/16**, no new model calls. F12 page-colon formatting repaired; F09 USD abbreviation and independently PDF-reviewed secondary quantity recorded in a separate reference version. Primary values/questions/pages unchanged.
- `live_web_demo`: actual browser screenshots of a live question, answer and clicked PDF page.
- `tests.xml`: 199 passed, 5 skipped before rescore changes. `tests_final_2026-10-02.xml`: **201 passed, 5 skipped** after evaluation changes. `tests_verified_2026-10-02.xml`: **202 passed, 5 skipped** after checking the portable CLI/schema compatibility.
- `freeze_audit.json`: service/route source hashes still match the fresh experiment. Evaluation changes are identified separately. Runtime was not tuned on fresh pilot answers.

All labels are AI visual reviews, not independent human certifications. The fresh questions concentrate on three pages and are a pilot, not a representative final thesis test. “Supported” in these scores means the numeric grader passes and a labeled page is in the returned sources. It does **not** certify sentence-level citation precision or correct cell identity in every excerpt.

## Reproduce (PowerShell, from repository root)

Use Python from the project environment. Configure PostgreSQL, local Ollama/bge-m3 and your own Vertex credentials. Do not put keys in this package. The experiment creates and removes its own uniquely named PostgreSQL database; this requires database-creation permission. Cloud answer runs use Gemini, not Qwen.

### Existing diagnostic database

The legacy PDF must first be ingested with provenance, as documented in the preceding postmerge package. Stop an API process that owns the same DuckDB file before running the direct benchmark. The script does not re-ingest or alter labels.

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_live_diagnostic --manifest TestFile/postmerge_2026-10-01_v1/legacy_reference_reviewed_v3.json --output outputs/my-diagnostic-run
```

### Download frozen public Thai PDFs and run the fresh experiment

```powershell
.\.venv\Scripts\python.exe -m scripts.download_benchmark_sources --manifest TestFile/runtime_repair_2026-10-01_v1/fresh_manifest.json --output outputs/fresh-pdfs
.\.venv\Scripts\python.exe -m scripts.benchmark_heldout_gemini --manifest TestFile/runtime_repair_2026-10-01_v1/fresh_manifest.json --corpus-dir outputs/fresh-pdfs --embedding-cache outputs/fresh-embeddings.npz --output outputs/my-fresh-run --answer-limit 16 --measure
```

Use a new output directory for each run. Downloaded files are checked against SHA-256 and page count. PDFs, model weights, production databases and embedding arrays are intentionally outside this source-control package. This run is native PDF text, not Typhoon/Gemini OCR, and has an empty isolated DuckDB.

### Reproduce corrected grading without model calls

```powershell
.\.venv\Scripts\python.exe -m backend.eval.score_layers answers --reference TestFile/runtime_repair_2026-10-01_v1/fresh_rescore_v2/reference_v2.json --predictions TestFile/runtime_repair_2026-10-01_v1/fresh_thai_pilot/app_gemini_answers.json --page-space source --out outputs/app-rescore-repeat.json
.\.venv\Scripts\python.exe -m backend.eval.score_layers answers --reference TestFile/runtime_repair_2026-10-01_v1/fresh_rescore_v2/reference_v2.json --predictions TestFile/runtime_repair_2026-10-01_v1/fresh_thai_pilot/bm25_gemini_answers.json --page-space source --out outputs/bm25-rescore-repeat.json
```

Count rows where `fact_status == "correct"` and `all_required_pages_cited == true` for the combined measure. Fact-only and source-page scores remain separate in each result.

### Real private workflow

Prefetch Docling/EasyOCR models first. Set `LOCAL_OCR_PYTHON`, `LOCAL_OCR_MODELS_DIR` and `LOCAL_OCR_EASYOCR_CACHE_DIR` to your installed local paths. Place the output outside OneDrive. Example:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_private_workflow --pdf backend/uploads/1testfile.pdf --question "จากไฟล์ 1testfile.pdf รายได้ดอกเบี้ยสุทธิปี 2568 เท่ากับกี่ล้านบาท?" --expected-fragment 137152 --output C:/LocalRagChecks/new-run
```

The expected-fragment check is a smoke check, not the strict numeric/citation benchmark; a future passing smoke check must still be strictly graded. The recorded run failed even this check. External DNS/TCP blocks are process-level, not an OS firewall measurement. No hosted fallback is used.

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest backend/eval/tests backend/services/tests -q
```

## Measurement limits

- SDK attempts include retries implemented by the application; hidden SDK retries are not counted.
- RSS samples are local processes, not cloud compute or complete GPU memory accounting. The Ollama process-name sample is not a total for every possible model-worker process.
- Runtime v7 and earlier runs have different cache/retry/background conditions; time differences are observations, not a controlled speedup claim.
- Baseline uses three BM25 chunks; app uses its own retrieval/context policy. This compares systems, not identical-context generation.
- Original outputs and hashes remain available even when a later rescore is preferred.
