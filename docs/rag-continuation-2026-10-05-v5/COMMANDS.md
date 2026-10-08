# Commands and reproducibility

Working directory: `C:\Users\nonga\OneDrive\Desktop\Project_2\Agentic_RAG_Business-Insight-Analysis`; Python `.venv\Scripts\python.exe`, `PYTHONUTF8=1`. Exact flags below exist in the included source; `--help` was checked for replay, storage repair and ingestion runners. Run outputs are immutable. Use a new output directory when reproducing.

## Final regression — actually executed, exit0 / 239 passed

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend/eval/tests backend/services/tests/test_llm_trace.py backend/services/tests/test_retrieval_rank.py backend/services/tests/test_page_context.py backend/services/tests/test_cross_report_evidence.py backend/services/tests/test_pdf_ingestion.py backend/services/tests/test_pipeline_provenance.py backend/services/tests/test_document_jobs.py backend/services/tests/test_cell_unit_context.py backend/services/tests/test_runtime_cell_provenance.py backend/services/tests/test_agent_evidence_budget.py backend/services/tests/test_financial_quality.py backend/services/tests/test_table_extraction.py backend/services/tests/test_table_chunk_limits.py -q --junitxml='C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\outputs\tests\regression_final.xml'
git diff --check -- backend/services/llm.py backend/services/duckdb_warehouse.py backend/services/tests/test_cell_unit_context.py
```

Earlier test snapshots: regression140, tracing focused11, meter7, then ingestion-related167, unit-related183. These are overlapping test populations, not additive counts. Final run contains 239 tests; a pre-existing Pydantic warning remains.

## Saved-answer replay — actually executed for v4 and v5, exit0 each

```powershell
$ragOld='C:\Users\nonga\Documents\Codex\2026-09-25\i-would-currently-rate-the-project\outputs\ranking_evidence_2026-10-05_v3'
$ragOut='C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\outputs'
.venv\Scripts\python.exe -m scripts.replay_contract_v2 --audit "$ragOld\smoke20_eval_judged" --answers "$ragOld\answer_smoke20\app_gemini_answers.json" --trace "$ragOld\answer_smoke20_audit\generation_trace.json" --labels "$ragOld\labels_v4\numeric_labels_v4_locked.json" --policy "$ragOld\labels_v4\evaluation_policy.json" --reference "$ragOld\labels_v4\reference_v4_locked.json" --numeric-annotations "$ragOut\numeric_answer_annotations_ai_review.json" --output "$ragOut\contract_replay20_v4_bound"
.venv\Scripts\python.exe -m scripts.replay_contract_v2 --audit "$ragOut\audit20_v5_visual_adjudication" --answers "$ragOld\answer_smoke20\app_gemini_answers.json" --trace "$ragOld\answer_smoke20_audit\generation_trace.json" --labels "$ragOut\labels_v5\numeric_labels_v5_locked.json" --policy "$ragOut\labels_v5\evaluation_policy.json" --reference "$ragOut\labels_v5\reference_v5_locked.json" --numeric-annotations "$ragOut\numeric_answer_annotations_ai_review.json" --output "$ragOut\contract_replay20_v5_visual"
```

These directories already exist. For another execution use `NEXT_ACTION.md` commands with a new scratch output path. Historical inputs are copied into this delivery and bind the same SHA256. Replays cost zero model calls. `reproduction_support/freeze_visual_correction.py` records the one-item versioned manual AI review; its fixed output names intentionally refuse overwriting an existing v5 bank.

## Paired retrieval rescore — available offline CLI

```powershell
.venv\Scripts\python.exe -m scripts.score_paired_retrieval_v4 --reference "$ragOut\historical_inputs\labels_v4\reference_v4_locked.json" --baseline "$ragOut\historical_inputs\baseline498\retrieval.json" --candidate "$ragOut\historical_inputs\lexical_first498\retrieval.json" --output 'C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\work\retrieval_rescore_next'
```

This recomputes metrics from preserved predictions; it is not new retrieval or new answer generation. Bootstrap seed2000 resamples uses the implemented fixed seed20261005. Source gold, raw predictions, paired recovered/regressed rows and summaries are included. Full original PDFs/index and existing repo services/config are dependencies for rerunning inference; they are not replaced by this score replay.

## Actual cloud run diary — completed, do not rerun these output paths

All runs used the same original budget file at `$ragOld\handoff_budget.json`.

```powershell
.venv\Scripts\python.exe -m scripts.run_ingestion_smoke_v4 --plan 'C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\work\ingestion_smoke4\plan.json' --budget "$ragOld\handoff_budget.json" --output "$ragOut\ingestion_smoke4_v4" --max-new-attempts 30 --run
.venv\Scripts\python.exe -m scripts.run_ingestion_smoke_v4 --plan 'C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\work\ingestion_smoke4\plan.json' --budget "$ragOld\handoff_budget.json" --output "$ragOut\ingestion_smoke4_v5_retry" --max-new-attempts 24 --resume-from "$ragOut\ingestion_smoke4_v4" --run
.venv\Scripts\python.exe -m scripts.serve_ingestion_review_v4 --run-dir "$ragOut\ingestion_smoke4_v5_retry" --budget "$ragOld\handoff_budget.json" --output "$ragOut\ui_ingestion_smoke4_v5" --port 18085
.venv\Scripts\python.exe -m scripts.run_ingestion_smoke_v4 --plan 'C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\work\ingestion_table1\plan.json' --budget "$ragOld\handoff_budget.json" --output "$ragOut\ingestion_table1_v6" --max-new-attempts 14 --run
.venv\Scripts\python.exe -m scripts.replay_table_unit_repair --source "$ragOut\ingestion_table1_v6" --truth 'C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\work\ingestion_table1\table_truth_locked.json' --output "$ragOut\ingestion_table1_v7_unit_repair" --budget "$ragOld\handoff_budget.json" --run
```

Initial run used6 calls; retry9 and exit1 at final409 resume audit; UI1; table11 exit0; repair6 exit0. The second run reuses the first isolated PostgreSQL/DuckDB and successful pages. The separate repair modifies only a new DuckDB copy, reads original evaluation PostgreSQL and consumes no OCR. Temporary UI server was stopped through `/__evaluation__/shutdown` and exited0. UI interactions/screenshots were performed through the actual in-app Browser.

Do not replay fresh-cloud commands after original deadline, widen global budgets, drop production DB, or reuse output directories. Resume initial upload assumes the selected documents still need resume; completed jobs return409. Idempotency checks at the end handle409. `--resume-from` is not a generic rerun of already-completed question outputs.

## Artifact sources and locks

`CODE_LOCK_FINAL.json` hashes the latest relevant source. Each experiment keeps its own earlier code snapshot and prompt/model traces. Source path portability was added to the storage replay after v7, so latest script hash differs from the frozen historical v7 script. The final source does not change scoring or agent behavior.

v6 did not freeze warehouse.py at execution time. `baseline_warehouse_reconstructed_from_HEAD.py` is an explicitly reconstructed baseline from the unchanged HEAD module (only the ten-line unit repair differs in current Git diff), not a contemporaneous code capture. Cached OCR, saved warehouse and baseline answers remain original artifacts.

Local offline verification and ZIP/hash checks are described in `PACKAGE_VERIFICATION.json`; `SHA256_MANIFEST.json` indexes final payload files. Original full-PDF paths and official download URLs remain in input plans / locked reference metadata. Selected upload derivatives and their original-page maps are included.
