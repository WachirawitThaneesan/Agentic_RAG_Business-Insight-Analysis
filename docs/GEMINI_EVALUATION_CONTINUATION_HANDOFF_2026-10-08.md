# Gemini evaluation continuation — 2026-10-08

User authorized continuing the work and opening a new chat. This handoff authorizes the new continuation chat to own the next work; the sending chat will stop repository work after registering the transfer. No parallel evaluation owner or subagent is needed.

## Authoritative instructions

Finish the Gemini evaluation and improve the actual system as far as practical before local Docling. All quality criteria have working target >80%; original targets remain aspirations for later detailed work. Do not manufacture passing scores or change gold facts/answers to improve metrics.

Latest explicit clarification: the quota the user wants to conserve is **Codex quota, not Gemini quota**. Necessary Gemini evaluation calls and useful controlled candidate experiments are permitted. Earlier broad judge stop was based on a mistaken resource interpretation. Keep evidence, failures, and cumulative metering. Conserve Codex through compact scripted analysis, batching independent reads, useful periodic updates, and avoiding duplicate work; do not continue the old blanket restriction on Gemini calls. Read `docs/EVALUATION_WORKING_POLICY_2026-10-08.json` v2 first.

## Workspace and state

Same local repository, many existing dirty/untracked changes: preserve them. No production DB writes, deletion, push/deploy, or human certification. No goal exists in app goal API last checked; do not create one from historical goal markdown. No owned evaluation Python workers were running at transfer preflight. Do not reopen the old failed B chat or start C/Docling yet.

Read `docs/evaluation-B-2026-10-08/STAGE5_RECOVERY_REPORT_th.md`, `docs/evaluation-B-2026-10-08/STAGE3_METRICS.json`, and `docs/NUMERIC_IDENTITY_SOURCE_DIAGNOSIS_2026-10-08.md` as needed. Newest policy overrides older hard gates and quota limits in historical notes.

Evidence root: `TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/`. Generation, corpus, labels, manifests, errors, and every attempted arm are retained. Ledger: `TestFile/evaluation_completion_2026-10-07/resource_ledger.json` — last recorded 3,872 attempts, 61,148,346 known input tokens, 2,038,266 known output tokens; 396 failed calls without complete usage. Lower bounds/unknowns remain, no reset or invented numeric cap/deadline.

## Current measured results

Online OCR implementation is Typhoon prose plus Gemini tables, not pure Gemini prose. Original selected table cells baseline123/169 -> candidate166/169=98.22%; selected development pages only. Fresh actual32-page ingestion has the same166/169 raw/stored cells,341chunks80rows; hashes/provenance/restart/idempotency/rollback checked on isolated DB. Source relationship year-guard audit118/185 strict lower bound63.78%,61 unknown;118/124=95.16% measured must not be called overall OCR accuracy. Text CER/WER/chart accuracy not measured.

Stage3 retrieval on498 development questions: lexical Hit@5/required recall465/498=93.37%; hybrid421/498=84.54%. OCR change did not change lexical Hit@5; don't claim retrieval improvement. Current full development corpus3617chunks has actual stored OCR substituted for32mapped pages;3339outsidechunks exact unchanged. Other pages are frozen historical/native, not full-report fresh production OCR.

`current20_paired_v1` + `current20_judge_v1`: both methods fully audited20answers, captured20/20, numeric3/8=37.5%. Contract complete success lexical15/20=75%, hybrid13/20=65%. Macro factual precision/faithfulness100% on19non-refusal answers; factual/context recall95%/100%, answer relevance95%; actual emitted citation precision/recall100% on applicable answers. Context precision lexical78.36%,hybrid73.16%. Source quote validation and strict tuples are separate; these AI scores do not imply all criteria passed.

`current50_paired_v1`: all100actual outputs generated (50per arm), retaining the exact20prefix including errors;50manifest freezes app v1.10. Hybrid capture48/50=96%,numeric7/19=36.84% with19/20coverage;lexical47/50=94%,numeric5/20=25% with20/20coverage. Both46/50non-refusal. This is development, not unseen. Do not resume generation into this old manifest with changed app code.

`current50_judge_v1` stopped intentionally67/100records,64measured+3failed: hybrid49valid,lexical15valid. Exact20prefix valid audits reused. Three failures B0194hybrid empty/nonJSON, B0062lexical empty/nonJSON, B0078lexical missingoriginalfragment. Remaining33records not audited. Contract hybrid31/50=62% complete lower bound with3unresolved16knownfail; lexical9/50=18% lower bound with35unresolved6knownfail, not a full50 success score. Use `contract_summary.json`/`contract_details.json`, not the legacy summary's complete score or citation_source_precision (counts retrieved contexts rather than actual emitted links).

## Existing application changes

Current `backend/services/answer_capture.py` is v1.11: native numeric.value NUMBER rather than STRING; AAA/AA/A ratings belong to qualitative fields. JSON numeric lexical precision preserved using Decimal then decimal strings only for numeric fields. Old v1.10 binding accepted. Offline68tests pass and95previously complete captured outputs still binding-valid. No live accuracy gain measured. Evidence `NATIVE_SCHEMA_OFFLINE_CHECKPOINT.json`; initial failed test fixture/XML retained.

Earlier repairs already done: full actual tool observation handoff in agent.py, USD abbreviation binding, real N/A fallback retaining literal N/A without inventing zero, empty audit-header normalization. Do not redo them or rerun passed broad tests without a material reason. Old outputs not rewritten.

## Next work, efficiently

1. Verify ownership/RUN_STATE and relevant frozen audit inputs. Complete the outstanding saved-answer Gemini judgments using existing valid matching cache. Judge only frozen actual outputs; do not regenerate successful historical answers. Inspect `scripts/audit_capture_run.py` resume/reuse behavior before dispatch. If the audit method freeze rejects changed code, create a new derived audit with exact matching valid verdict reuse and disclose lineage; don't bypass it. Operational retries of failed schema/quotes permitted; retain failures and don't retry a known-wrong answer merely to raise the headline.
2. In parallel only where independent, produce a compact deterministic failure inventory of both50numeric outputs: wrong value vs entity/measure identity vs year/unit/comparator vs missing evidence/false refusal. Read original bound sources/PDF when needed. Prior18literal-identity diagnoses are not auto passes. Don't change scorer/aliases based on emitted wording to improve scores. Distinguish genuine app errors from reference/scorer limitations with source-backed evidence and versioned comparisons.
3. Fix general application/extraction/context causes supported by evidence; focus on numeric correctness/complete-answer failures. Examples: B0078 target2030/2573 wrongly rendered report2567, source EGCO90 extraction missing2030; B0184 within30days should have bound/lte comparator, not eq; B0263 false refusal; B0062 verbose narrative hides genuine numeric quantities; B0072 AAA type fix only addresses typing, not extra unsupported/duplicated quantities. No gold injection or question-ID special cases. B0027/B0132/B0315 and legal issuer/freeword measure mismatches need source review, not aliases to make scores pass.
4. Preregister a useful small candidate comparison including former pass controls and failure categories, freeze current candidate code/source/data, preserve baseline answers and all new outcomes. Gemini calls are allowed where they resolve the issue; don't start costly unrelated sweeps or retry until a desired answer appears. Use appropriate focused tests and actual baseline/candidate metrics with denominators/regressions/resource usage.
5. Report the economical Gemini checkpoint honestly, including unmet >80% criteria and what is not measured. Continue the planned Gemini work until a defensible best-effort result; move to final/new-report evaluation or Docling only with clear stage handoff. No premature complete claim.

Keep summaries compact and send only meaningful updates. User specifically wants the work done while saving Codex quota; no need for repeated authorization questions for already authorized reversible fixes and necessary evaluations.
