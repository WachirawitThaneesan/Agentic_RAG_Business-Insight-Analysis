# Completed examination report and evaluation — 13 October 2026

The existing first-answer evaluation is complete: **1,060/1,060 usable AI-assisted assessments; zero remaining**. The English examination report and A1 poster use the same completed manifest. Original official project identities and the second academic term of 2568 are preserved.

| Frozen primary criterion | S0 Dense RAG | S1 Full App |
|---|---:|---:|
| Strict complete answers |79/498 (15.86%)|60/498 (12.05%)|
| Required numerical relations |119/356 (33.43%)|106/356 (29.78%)|
| Appropriate control abstentions |24/32 (75.00%)|28/32 (87.50%)|

Strict completion includes source facts, reference coverage, captured tuples, actual citations and explicit PDF-page wording. It is not ordinary answer accuracy. All assessments are complete; some claim metrics remain genuinely non-applicable. The >80% quality goal remains false. Judgments are AI-assisted with no independent human confirmation; reviewer assignment was neither randomized nor blind.

## Files

- `artifacts/examination_report.docx` and `.pdf`: editable report and 24-page final PDF.
- `artifacts/project_poster_A1.svg`, `.html`, `.pdf`, `.png`: editable vectors, editable print layout, A1 print PDF and preview.
- `EVALUATION_OVERVIEW.html`: offline read-only viewer with filters for all 1,060 rows.
- `artifacts/report_previews/`: all 24 visually inspected final report page PNGs.
- `report_poster_evaluation_bundle.zip`: all final deliverables, editable sources and concise audit records.
- `RESULT_MANIFEST_v2.json`, `RESULTS_BY_QUESTION.json`: primary summary, metric denominators, paired uncertainty and per-question results.
- `HISTORICAL_RESULT_MANIFEST_v1.json`: earlier incomplete checkpoint, preserved separately.

## Completion and correction provenance

The earlier 712 usable assessments were retained; 348 append-only completion overlays use saved historical response components and Codex decisions for missing judgments. There were **zero new Gemini calls** and no new application answers. A separate layer contains 34 consistency adjudications. Original first outcomes, judgments, source labels, scorer and earlier manifest were not overwritten: 2,124 original file hashes and 239 frozen application-code hashes were verified. Refusals, capture errors and completed wrong answers were retained.

The scorer was replayed with four path constants substituted. Sixteen null annotation-collection fields were projected to empty lists only. No tuple metadata was inferred or postfilled to create a pass. Finer-precision source-supported quantities can fail the exact frozen numerical criterion while remaining factual. Historical evidence transcripts are AI-derived unless a literal native quote has separately been verified; provider metadata alone is not verification.

Three defective frozen source labels are disclosed: KCE01q09 compares different product scopes; OSP08q12 uses two same-year reporting-scope columns as prior/current years; KCE08q02 mistakes the fixed-rate-only zero subgroup for total separate long-term debt. A **separate paired sensitivity** excludes these same three questions for both systems: S0 79/495 strict and 119/353 numeric; S1 59/495 strict and 105/353 numeric. Primary denominators remain 498 and 356. No development scores were relabeled unseen.

## Validation and scope

All 1,060 assessments passed the frozen schema/coverage validator and score arithmetic checks. The report was rendered with Microsoft Word COM after diagnosing the packaged renderer's missing LibreOffice executable; all three contents/list fields were updated. All 24 pages and the A1 poster were visually checked. Related frozen runtime tests: **96 passed**, with one existing Pydantic deprecation warning.

Known historical Gemini token components are partial uncached estimates, not invoices: ingestion $3.436368; S0 queries $4.0740207; S1 queries $5.6102502. Missing usage, thinking, cache, Codex account allocation, local hardware/energy and other unknown costs are not priced. The application/storage/embeddings are local; historical OCR/generation used cloud services. The project is not fully offline.

`python verify_release.py` verifies release hashes, paired counts, aggregate metrics and sensitivity from published rows without APIs or databases. `python scripts/show_project_status.py --once` from the repository root displays the saved status; Windows users can open `Open_Project_Status.cmd`. The published decision archive omits raw source quotations and the generation corpus. Full source-aware adjudication/replay requires the preserved private evidence directories and original issuer PDFs listed in SOURCE_REPORTS.json; this public package is not an independently human-adjudicated benchmark.

`build_submission.py` preserves the editable layout and uses public measurement/identity metadata. It needs Python 3.12+ and python-docx; the existing workflow/result PNGs are included. Run `python build_submission.py assets` for vector sources and `python build_submission.py` for DOCX. PDF export still needs a compatible Word/LibreOffice renderer and visual rechecking. No task here invokes a model.
