# Commands and failed experiments

PowerShell, repo cwd, `$env:PYTHONUTF8='1'`; Python `.venv/Scripts/python.exe`. Exact inputs in `TestFile/evaluation_A_2026-10-08/gemini_ocr/inference_inputs_locked.json`. Inference rejects `--references`; references never enter Gemini requests

Live generation used this command sequentially with output names `live_baseline_v1`, `live_candidate_v1`, `live_candidate_v2` and their saved code/prompt hashes. **Do not rerun generation merely to reproduce metrics.**

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_gemini_ocr_stage_a --generate --inputs TestFile/evaluation_A_2026-10-08/gemini_ocr/inference_inputs_locked.json --budget TestFile/evaluation_completion_2026-10-07/resource_ledger.json --output TestFile/evaluation_A_2026-10-08/gemini_ocr/live_candidate_v2
```

Offline reproduction (choose a new output name; old evidence is not overwritten):

```powershell
.venv/Scripts/python.exe -m scripts.replay_gemini_header_repair --source TestFile/evaluation_A_2026-10-08/gemini_ocr/live_candidate_v2 --output TestFile/evaluation_A_2026-10-08/gemini_ocr/reproduction_new --baseline-code TestFile/evaluation_A_2026-10-08/gemini_ocr/baseline_code/backend/services/gemini_tables.py --references TestFile/evaluation_A_2026-10-08/gemini_ocr/references_v3_locked.json
```

Offline scoring uses the same scorer for every saved arm:

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_gemini_ocr_stage_a --output TestFile/evaluation_A_2026-10-08/gemini_ocr/live_baseline_v1 --references TestFile/evaluation_A_2026-10-08/gemini_ocr/references_v3_locked.json
```

Capture replay command was `.venv/Scripts/python.exe -m scripts.replay_stage_a_capture` (script refuses to overwrite its output). Trace hashes and immutable-answer checks in `stage2_capture_replay/summary.json`. All532answers remain in scope, including53without matching raw generation. Judge failures are classified, not rejudged

Broad tests:

```powershell
.venv/Scripts/python.exe -m pytest backend/eval/tests backend/services/tests/test_answer_capture.py backend/services/tests/test_numeric_capture_identifiers.py backend/services/tests/test_stored_table_evidence.py backend/services/tests/test_stage_a_ocr_cells.py backend/services/tests/test_gemini_table_routing.py backend/services/tests/test_cell_unit_context.py backend/services/tests/test_financial_quality.py backend/services/tests/test_table_extraction.py backend/services/tests/test_pdf_layout.py backend/services/tests/test_document_jobs.py backend/services/tests/test_source_provenance.py backend/services/tests/test_table_response_provenance.py backend/services/tests/test_query_capture_log.py -q
.venv/Scripts/python.exe -m pytest backend/services/tests/test_stored_table_evidence.py backend/services/tests/test_table_chunk_limits.py -q
```

Failed/rejected work retained: initial page-render call used wrong `plan_pdf_regions` signature and did not reach cloud; one candidate preflight import had an unclosed schema brace, repaired before actual SDK dispatch; one test command named nonexistent `test_table_utils.py` and ran no tests. Candidate1 regressed units/row names; candidate2 prompt-only lost compound headers. Unvalidated continuation prototype was withdrawn after correcting source review. AllSDKerror attempts(6)remain in journals/ledger. No successful response was selected using gold scores
