# Verified commands and continuation

Run from the repository root with .venv/Scripts/python.exe and PYTHONUTF8=1. The final133_v2 generator has finished all532 outputs; no new generation is needed.

## Current checks

The active controller is scripts.resume_final_evaluation. It runs two judgment workers, preserves all saved outcomes, and packages results after the authoritative replay finishes. Do not start a duplicate controller, generator or the older supervisor.

```powershell
Get-Content TestFile/evaluation_completion_2026-10-07/RUN_STATE.json
Get-Content TestFile/evaluation_completion_2026-10-07/interruption_recovery_v1/progress.json
```

The current logs are interruption_recovery_v1/{main_resume,dense_resume,simple_rag_resume,launcher_error}.log. The original final_judge.log and final_judge_shards logs are historical and preserved.

If a worker ends unexpectedly, verify its recorded PID is no longer running, archive its model_calls.json/budget_checkpoint.json and launcher marker, then resume the same frozen audit. Never reset the cumulative ledger. --resume skips saved judge outcomes and validates the method lock. A cold meter starts a new call journal, so archive the old journal first. If any ledger checkpoint is unreadable, restore the latest valid global checkpoint and disclose uncheckpointed usage as unknown.

## Offline reproduction

After all outcomes are recorded:

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -m scripts.package_evaluation_completion --final
.venv/Scripts/python.exe -m scripts.verify_final_completion
```

These commands generate no model calls. The verifier checks all532 generation/judge outcomes, frozen backend/input hashes, exact judge payloads and offline metric reproduction. Failed judgments remain failed/unresolved. Package creation verifies ZIP CRC and every indexed file SHA. It also reconciles the canonical ledger only if its original/previous hash still matches; concurrent changes are preserved.

final_input_snapshot includes the native corpus/cache/labels and original public PDFs. Historical integration evidence and delivery orchestration source are bundled separately from the original inference freeze. Live DuckDB files, runtime locks and resource-sample logs are excluded. No credentials/.env/model weights are included.

## Operational repairs

- First technical restart: nullable keyword similarity/follow-up query cache; seven question IDs had partial exposure. No performance-driven tuning.
- Windows file-lock recovery:184 matching saved outputs plus original pending output185 recovered; existing DB/outputs resumed without regenerating paid answers.
- Later worker interruption:200 saved judgments survived; four latest files were unreadable. Latest valid ledger SDK=2909 was restored, old/corrupt journals retained, flush/fsync added before atomic checkpoint replacement. Subsequent SDK/token totals are lower bounds for potentially uncheckpointed usage.
- Parallel scheduling publishes measured and failed outcomes only when every payload field matches. Existing authoritative caches win regardless of score; overlapping calls/outcomes remain recorded.

## Verification evidence

- final_driver_repair.xml:257 regression tests passed.
- durable_checkpoint_recovery.xml:11 checkpoint/ledger checks passed (overlaps earlier tests; do not sum these as distinct cases).
- final_numeric_components:all four diagnostic state/count totals reproduce their original strict numeric summaries, zero cloud calls.
- final_retrieval:118 answerable questions,15 controls excluded, zero cloud calls.
- Scoped whitespace checks passed. The checkout includes pre-existing dirty work. No commit/push/deploy or production DB deletion.
