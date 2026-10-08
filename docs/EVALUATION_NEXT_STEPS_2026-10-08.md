# Evaluation Progress and Next Steps — 8 October 2026

This document is the current plan. It supersedes historical progress estimates and active-run statements in earlier handoffs. The adviser-facing [English report](GEMINI_RAG_FULL498_REPORT_2026-10-08.md) presents the positive results first and discusses the remaining integration challenges as future work.

## Completed Development Evaluation

All **498 development questions** have saved system outputs and valid AI evaluation records. Eight RAG quality metrics exceed 80% using conservative aggregation over the entire set, with scores from **85.96% to 96.69%**. Missing or not-applicable question-level scores contribute zero, and the denominator remains 498.

The results belong to the frozen full498 run, whose capture version is v1.16. The current application capture version is v1.22; a new full498 live score has not been measured for v1.22. The question set is development data, and the results are AI provisional rather than independently human-certified or unseen-report results.

| Work Group | Stages | Completed Work | Remaining Work |
|---|---|---|---|
| A — Data and answer binding | 2 + 4 | Selected table-cell repair; source provenance; emitted claim/citation capture; tested calendar, range, currency, and quote-binding repairs | Full numerical relationships, question/reference ambiguities, year and entity roles, wider extraction validation |
| B — Retrieval and actual ingestion | 3 + 5 | Retrieval measured on 498 questions; actual isolated 32-page ingestion; restart, idempotency, rollback, and stored-data provenance checks; full498 saved-answer audit | Improve evidence completeness and page consistency; revalidate any subsequent system changes |
| C — Final evaluation and delivery | 6 + 7 | English development report, metric coverage, figures, archived evidence, and continuation plan | Freeze a selected configuration, evaluate previously unseen reports, obtain independent review, and deliver the final evaluation |

Docling remains deferred. The current task focuses on Gemini-assisted evaluation using **Typhoon prose extraction, Gemini table extraction, and Gemini answer generation**.

## Supporting Results

- Selected OCR table cells improved from **123/169 (72.78%) to 166/169 (98.22%)**, with 43 recoveries and no regression in that cell set. This is a selected development-page result, not overall OCR accuracy for all reports.
- Fresh ingestion of **32 pages** produced **341 chunks and 80 structured rows**, retaining the same 166/169 raw/stored cell result on an isolated database.
- Retrieval on the 498-question development set achieved **465/498 (93.37%)** for lexical-first and **421/498 (84.54%)** for hybrid under the recorded retrieval evaluation. This is separate from answer accuracy, and it is not attributed to OCR improvement.
- The full498 audit has no outstanding operational judge failures. Contract-level unresolved judgments remain explicit.

## Application and Evaluation Updates

The current changes preserve actual claim-to-source links, original PDF-page provenance, stored table evidence, and embedding/chunk bindings. The agent receives captured tool evidence and emits canonical structured claims. Model-call tracing records actual attempts, usage, reasoning budgets, and cancellation/error outcomes. The frontend displays the captured claim citations and escapes answer text.

Deterministic capture repairs distinguish calendar dates and base years from quantities, preserve full foreign-currency units, prevent a budget noun from becoming an approximate comparator, and bind the primary numerical clause while retaining full-claim quantity coverage. Range metadata uses the emitted endpoints rather than an artificial midpoint.

A controlled experiment covered **all 94 numerical questions / 102 required relationships**, plus four qualitative controls. Complete capture rose from **83/98 to 92/98**, but strict numerical success fell from **18/102 to 17/102**, with three recoveries and four regressions. The candidate schema/prompt changes were therefore **not selected**. The default native schema and instruction were restored to the frozen v1.16 block; verified deterministic binding repairs were retained separately. The candidate is not substituted for the full498 results.

## Technical Challenges and Future Work

The complete-answer contract requires every condition for an answer to pass simultaneously. Its current baseline is **302/498 (60.64%)**, with 59 unresolved answers. The numerical contract requires value, unit, entity, measure, year, document, page, and comparison condition to align; its current baseline is **18/102 (17.65%)**, with 15 unresolved relationships. Neither diagnostic is equivalent to the eight individual RAG quality metrics.

The next work is ordered as follows:

1. **Review source and question requirements independently.** Use the prepared packet of all 94 numerical questions and original PDF evidence before inspecting application outputs. Compare the independently derived requirements with the preserved 102-relation contract. Record unresolved layout, reporting scope, entity, year, or page ambiguities.
2. **Separate evaluation ambiguities from application errors.** Preserve the current labels and scores. Any justified reference or measurement correction must have source evidence, a new version, and equal remeasurement of baseline and candidate systems. Do not add aliases from application wording merely to improve scores.
3. **Implement a source-supported system repair.** Focus on missing required facts, numerical roles, performance versus target/report years, entity scope, and consistent page attribution. Use focused regression controls before expanding a new candidate.
4. **Evaluate the selected configuration on all 498 questions.** Keep every first outcome, error, abstention, regression, and unknown. Reuse only valid judgments with matching question, answer, and evidence inputs. Do not cherry-pick outputs from different candidates.
5. **Freeze and evaluate unseen reports.** Keep development and unseen results separate. Add independent human review and measure extraction dimensions that are still unreported, including text CER/WER and chart relationships where relevant.
6. **Deliver the final report and then plan Docling separately.** Retain method versions, denominator definitions, source hashes, failed attempts, and resource accounting.

## Validation and Resource Accounting

The local service/evaluation suites completed with **470 passed and 5 skipped**. The skips are opt-in live database tests; they are not counted as passed. Earlier compatibility verification confirmed that **529 saved complete captures** remain binding-valid. These checks establish implementation and artifact integrity, not attainment of every quality target.

The cumulative ledger is preserved: **5,787 SDK attempts**, **100,418,993 known input tokens**, **3,734,927 known output tokens**, and **547 failed calls without complete usage**. Recorded paid OCR pages remain 75. These are cumulative figures, not the incremental cost of the full498 run; unknown usage and unknown monetary cost are retained. Publication does not run additional model/OCR evaluations.

## Publication and Continuation

The requested publication branch is **`auto1`**, using the repository-local identity **66070026-Jakkrapat <66070026@kmitl.ac.th>**. Publishing code, reports, plans, and selected evidence is authorized by the user. Production database writes and deployment are outside this publication task.

Readable results and lossless selected archives are in [the publication package](../TestFile/published_2026-10-08/README.md). All original local experiments remain intact. Source PDFs, runtime databases/logs, and the complete 7.4 GB local experiment collection are not added to regular Git history. The package explains its exact scope and checksum verification; it does not claim that all local experiments are archived.

No evaluation worker is currently running. Continue from the source-review step above; the overall quality objective remains open.
